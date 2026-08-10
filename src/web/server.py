"""Dependency-free local HTTP server for the research console."""

from __future__ import annotations

import json
import mimetypes
import subprocess
import sys
import threading
import uuid
import webbrowser
from datetime import date, datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from src.storage.tier2_repository import Tier2Repository
from src.storage.tier3_repository import Tier3Repository

from .dashboard import DashboardService

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = Path(__file__).resolve().parent / "static"
MAX_BODY = 1_000_000


class JobRegistry:
    """Small in-memory registry for long-running CLI operations."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def start(self, command: list[str], label: str) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        job = {
            "job_id": job_id,
            "label": label,
            "status": "RUNNING",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "output": "",
            "return_code": None,
        }
        with self._lock:
            self._jobs[job_id] = job
        thread = threading.Thread(
            target=self._run, args=(job_id, command), daemon=True
        )
        thread.start()
        return dict(job)

    def _run(self, job_id: str, command: list[str]) -> None:
        try:
            result = subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60 * 60,
                check=False,
            )
            output = (result.stdout + "\n" + result.stderr).strip()[-20_000:]
            status = "SUCCEEDED" if result.returncode == 0 else "FAILED"
            return_code = result.returncode
        except Exception as exc:  # pragma: no cover - defensive job boundary
            output = str(exc)
            status = "FAILED"
            return_code = -1
        with self._lock:
            self._jobs[job_id].update(
                {
                    "status": status,
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "output": output,
                    "return_code": return_code,
                }
            )

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            values = [dict(job) for job in self._jobs.values()]
        return sorted(values, key=lambda item: item["started_at"], reverse=True)[:20]


def build_handler(db_path: str | Path, jobs: JobRegistry | None = None):
    service = DashboardService(db_path)
    registry = jobs or JobRegistry()
    db = str(db_path)

    class ConsoleHandler(BaseHTTPRequestHandler):
        server_version = "GoldenPitConsole/1.0"

        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write("[web] " + fmt % args + "\n")

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/api/overview":
                    run_id = parse_qs(parsed.query).get("run_id", [None])[0]
                    self._json(HTTPStatus.OK, service.overview(run_id))
                    return
                if parsed.path == "/api/jobs":
                    self._json(
                        HTTPStatus.OK,
                        {
                            "jobs": registry.list(),
                            "running_runs": service.running_runs(),
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
                if parsed.path == "/api/workflows":
                    self._start_workflow(body)
                elif parsed.path == "/api/actions/export-tier2":
                    self._export_tier2(body)
                elif parsed.path == "/api/actions/resume-tier1":
                    self._resume_tier1(body, data_retry=False)
                elif parsed.path == "/api/actions/retry-tier1-data":
                    self._resume_tier1(body, data_retry=True)
                elif parsed.path == "/api/reviews/stage-b":
                    self._review_stage_b(body)
                elif parsed.path == "/api/reviews/stage-c":
                    self._review_stage_c(body)
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})
            except (ValueError, KeyError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:  # pragma: no cover - HTTP safety boundary
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

        def _start_workflow(self, body: dict[str, Any]) -> None:
            as_of = str(body.get("as_of", "")).strip()
            try:
                date.fromisoformat(as_of)
            except ValueError as exc:
                raise ValueError("筛选日期必须是 YYYY-MM-DD") from exc
            scope = str(body.get("scope", "symbols")).strip().lower()
            if scope not in {"market", "symbols"}:
                raise ValueError("scope 必须为 market 或 symbols")
            symbols = body.get("symbols", [])
            if isinstance(symbols, str):
                symbols = [item for item in symbols.replace(",", " ").split() if item]
            clean_symbols = []
            for value in symbols:
                symbol = str(value).strip().upper()
                if symbol.endswith((".SH", ".SZ", ".BJ")):
                    symbol = symbol[:-3]
                if not symbol.isdigit() or len(symbol) > 6:
                    raise ValueError(f"无效股票代码: {value}")
                clean_symbols.append(symbol.zfill(6))
            if scope == "symbols" and not clean_symbols:
                raise ValueError("请至少输入一个股票代码")
            command = [
                sys.executable,
                str(PROJECT_ROOT / "main.py"),
                "workflow",
                "--as-of",
                as_of,
                "--db",
                db,
            ]
            if scope == "symbols":
                command.extend(["--symbols", *dict.fromkeys(clean_symbols)])
            label = (
                f"{as_of} 全市场 Stage A 筛选"
                if scope == "market"
                else f"{as_of} Stage A 筛选（{len(set(clean_symbols))} 只）"
            )
            job = registry.start(command, label)
            self._json(HTTPStatus.ACCEPTED, {"job": job})

        def _export_tier2(self, body: dict[str, Any]) -> None:
            run_id = self._required(body, "run_id")
            symbols = body.get("symbols") or []
            command = [
                sys.executable,
                str(PROJECT_ROOT / "main.py"),
                "export-tier2",
                "--run-id",
                run_id,
                "--db",
                db,
            ]
            if symbols:
                command.extend(["--symbols", *[str(item) for item in symbols]])
            job = registry.start(command, "生成 Stage B 证据包")
            self._json(HTTPStatus.ACCEPTED, {"job": job})

        def _resume_tier1(
            self, body: dict[str, Any], *, data_retry: bool
        ) -> None:
            run_id = self._required(body, "run_id")
            symbols = body.get("symbols") or []
            command = [
                sys.executable,
                str(PROJECT_ROOT / "main.py"),
                "retry-tier1-data" if data_retry else "resume-tier1",
                "--run-id",
                run_id,
                "--db",
                db,
            ]
            if symbols:
                command.extend(["--symbols", *[str(item) for item in symbols]])
            label = (
                "Stage A 数据缺口补跑" if data_retry else "Stage A 断点续跑"
            )
            job = registry.start(command, label)
            self._json(HTTPStatus.ACCEPTED, {"job": job})

        def _review_stage_b(self, body: dict[str, Any]) -> None:
            review_id = Tier2Repository(db).save_human_review(
                assessment_id=self._required(body, "assessment_id"),
                decision=self._decision(body),
                reviewer=self._required(body, "reviewer"),
                rationale=self._required(body, "rationale"),
                expected_run_id=self._required(body, "run_id"),
                expected_symbol=self._required(body, "symbol"),
            )
            self._json(HTTPStatus.CREATED, {"review_id": review_id})

        def _review_stage_c(self, body: dict[str, Any]) -> None:
            review_id = Tier3Repository(db).save_human_review(
                risk_assessment_id=self._required(body, "risk_assessment_id"),
                decision=self._decision(body),
                reviewer=self._required(body, "reviewer"),
                rationale=self._required(body, "rationale"),
                expected_run_id=self._required(body, "run_id"),
                expected_symbol=self._required(body, "symbol"),
            )
            self._json(HTTPStatus.CREATED, {"review_id": review_id})

        @staticmethod
        def _required(body: dict[str, Any], key: str) -> str:
            value = str(body.get(key, "")).strip()
            if not value:
                raise ValueError(f"缺少字段: {key}")
            return value

        @staticmethod
        def _decision(body: dict[str, Any]) -> str:
            decision = str(body.get("decision", "")).upper()
            if decision not in {"PASS", "REVIEW", "REJECT"}:
                raise ValueError("decision 必须为 PASS、REVIEW 或 REJECT")
            return decision

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
            if relative not in {"index.html", "styles.css", "app.js"}:
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
    print(f"黄金坑研究控制台已启动: {url}")
    print("按 Ctrl+C 停止服务")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止服务…")
    finally:
        server.server_close()
