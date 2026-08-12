"""Dependency-free local HTTP server for the research console."""

from __future__ import annotations

import json
import mimetypes
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from src.execution import JobRegistry
from src.strategies import StrategyRegistry, build_strategy_registry

STATIC_ROOT = Path(__file__).resolve().parent / "static"
MAX_BODY = 1_000_000


def build_handler(
    db_path: str | Path,
    jobs: JobRegistry | None = None,
    strategies: StrategyRegistry | None = None,
):
    registry = jobs or JobRegistry()
    strategy_registry = strategies or build_strategy_registry(db_path)

    class ConsoleHandler(BaseHTTPRequestHandler):
        server_version = "GoldenPitConsole/1.0"

        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write("[web] " + fmt % args + "\n")

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                parts = parsed.path.strip("/").split("/")
                if parsed.path == "/api/strategies":
                    self._json(
                        HTTPStatus.OK, {"strategies": strategy_registry.catalog()}
                    )
                    return
                if (
                    len(parts) == 4
                    and parts[:2] == ["api", "strategies"]
                    and parts[3] == "overview"
                ):
                    run_id = parse_qs(parsed.query).get("run_id", [None])[0]
                    self._json(
                        HTTPStatus.OK,
                        strategy_registry.get(parts[2]).overview(run_id),
                    )
                    return
                if parsed.path == "/api/overview":
                    run_id = parse_qs(parsed.query).get("run_id", [None])[0]
                    self._json(
                        HTTPStatus.OK,
                        strategy_registry.get("golden-pit").overview(run_id),
                    )
                    return
                if parsed.path == "/api/jobs":
                    running_runs = [
                        run
                        for module in strategy_registry.modules()
                        for run in module.running_runs()
                    ]
                    self._json(
                        HTTPStatus.OK,
                        {
                            "jobs": registry.list(),
                            "running_runs": running_runs,
                        },
                    )
                    return
                self._static(parsed.path)
            except ValueError as exc:
                self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
            except Exception as exc:  # pragma: no cover - HTTP safety boundary
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                body = self._body()
                parts = parsed.path.strip("/").split("/")
                if len(parts) == 5 and parts[:2] == ["api", "strategies"] and parts[3] == "actions":
                    self._handle_strategy_action(parts[2], parts[4], body)
                    return
                legacy_actions = {
                    "/api/workflows": "run",
                    "/api/actions/export-tier2": "export-evidence",
                    "/api/actions/resume-tier1": "resume",
                    "/api/actions/retry-tier1-data": "retry-data",
                    "/api/reviews/stage-b": "review-stage-b",
                    "/api/reviews/stage-c": "review-stage-c",
                }
                action = legacy_actions.get(parsed.path)
                if action:
                    self._handle_strategy_action("golden-pit", action, body)
                    return
                self._json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})
            except (ValueError, KeyError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:  # pragma: no cover - HTTP safety boundary
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

        def _handle_strategy_action(
            self, strategy_id: str, action: str, body: dict[str, Any]
        ) -> None:
            operation = strategy_registry.get(strategy_id).handle_action(action, body)
            if operation.kind == "job":
                job = registry.start(list(operation.command), operation.label)
                self._json(operation.status, {"job": job})
                return
            self._json(operation.status, operation.payload)

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY:
                raise ValueError("请求体为空或过大")
            content_type = self.headers.get("Content-Type", "")
            if "application/json" not in content_type:
                raise ValueError("仅支持 application/json")
            try:
                value = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("JSON 格式无效") from exc
            if not isinstance(value, dict):
                raise ValueError("请求体必须是 JSON 对象")
            return value

        def _static(self, path: str) -> None:
            relative = "index.html" if path in {"", "/"} else unquote(path.lstrip("/"))
            allowed = (
                relative in {"index.html", "styles.css", "app.js"}
                or relative.startswith("strategies/") and relative.endswith(".js")
            )
            if not allowed or ".." in Path(relative).parts:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            file_path = STATIC_ROOT / relative
            if not file_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content = file_path.read_bytes()
            mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{mime}; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)

        def _json(self, status: HTTPStatus, value: Any) -> None:
            content = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)

    return ConsoleHandler


def run_server(
    db_path: str | Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    server = ThreadingHTTPServer((host, port), build_handler(db_path))
    url = f"http://{host}:{port}"
    print(f"多策略选股研究平台已启动: {url}")
    print("按 Ctrl+C 停止服务")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止服务…")
    finally:
        server.server_close()
