import json
import threading
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

import pytest

from src.strategies.contracts import StrategyDescriptor, StrategyOperation
from src.strategies.registry import StrategyRegistry, build_strategy_registry
from src.web.server import build_handler


class ExampleStrategy:
    descriptor = StrategyDescriptor(
        strategy_id="example",
        name="示例策略",
        short_name="示例",
        description="验证策略模块可以独立接入。",
        version="v1",
        ui_module="/strategies/example.js",
    )

    def catalog_entry(self):
        return {**self.descriptor.as_dict(), "metrics": [], "latest_run": None}

    def overview(self, run_id=None):
        return {"strategy": self.descriptor.as_dict(), "run_id": run_id}

    def running_runs(self):
        return []

    def handle_action(self, action, body):
        if action != "run":
            raise ValueError(f"不支持动作: {action}")
        return StrategyOperation(
            kind="job",
            status=HTTPStatus.ACCEPTED,
            label="示例任务",
            command=("example-command", str(body.get("value", ""))),
        )


class RecordingJobs:
    def __init__(self):
        self.command = None

    def start(self, command, label):
        self.command = command
        return {"job_id": "example-job", "label": label, "status": "RUNNING"}

    def list(self):
        return []


def test_default_registry_exposes_two_contract_driven_strategies(tmp_path):
    catalog = build_strategy_registry(tmp_path / "strategies.db").catalog()

    assert [item["id"] for item in catalog] == ["golden-pit", "high-dividend"]
    assert catalog[0]["ui_module"] == "/strategy-assets/golden-pit/app.js"
    assert catalog[0]["ui_template"] == "/strategy-assets/golden-pit/template.html"
    assert catalog[0]["metrics"][0] == {
        "key": "universe",
        "label": "覆盖股票",
        "value": 0,
    }
    assert catalog[1]["ui_module"] == "/strategy-assets/high-dividend/app.js"


def test_registry_rejects_duplicate_strategy_ids():
    with pytest.raises(ValueError, match="重复注册"):
        StrategyRegistry([ExampleStrategy(), ExampleStrategy()])


def test_generic_http_layer_dispatches_registered_strategy(tmp_path):
    jobs = RecordingJobs()
    strategies = StrategyRegistry([ExampleStrategy()])
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        build_handler(tmp_path / "web.db", jobs, strategies),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        catalog_url = f"http://127.0.0.1:{server.server_port}/api/strategies"
        with urlopen(catalog_url) as response:
            catalog = json.loads(response.read())
        with urlopen(
            f"http://127.0.0.1:{server.server_port}/api/strategies/example/overview?run_id=run-1"
        ) as response:
            overview = json.loads(response.read())
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/strategies/example/actions/run",
            data=json.dumps({"value": "payload"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            operation = json.loads(response.read())

        assert catalog["strategies"][0]["id"] == "example"
        assert overview["run_id"] == "run-1"
        assert operation["job"]["job_id"] == "example-job"
        assert jobs.command == ["example-command", "payload"]
    finally:
        server.shutdown()
        server.server_close()


def test_strategy_frontend_asset_is_served_from_strategy_module(tmp_path):
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), build_handler(tmp_path / "assets.db")
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(
            f"http://127.0.0.1:{server.server_port}/strategy-assets/golden-pit/app.js"
        ) as response:
            content = response.read().decode("utf-8")
        with urlopen(
            f"http://127.0.0.1:{server.server_port}/strategy-assets/golden-pit/template.html"
        ) as response:
            template = response.read().decode("utf-8")
        with urlopen(f"http://127.0.0.1:{server.server_port}/") as response:
            shell = response.read().decode("utf-8")

        assert response.status == HTTPStatus.OK
        assert "StrategyConsole.register" in content
        assert 'data-strategy-page="golden-pit"' in template
        assert 'data-strategy-page="golden-pit"' not in shell
        assert 'id="strategyWorkspace"' in shell
    finally:
        server.shutdown()
        server.server_close()
