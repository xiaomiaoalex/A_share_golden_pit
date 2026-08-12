import json
import threading
from datetime import date
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

from config.tier1 import Tier1Config
from src.data.point_in_time.contracts import DataEnvelope, FetchStatus
from src.screening.tier1_v2.decision import evaluate_tier1
from src.storage.tier1_repository import Tier1Repository
from src.strategies.golden_pit.presentation import _tier2_assessment_view
from src.web.dashboard import DashboardService
from src.web.server import _bind_server, build_handler, prepare_database
from tests.unit.test_tier1_decision import decision_input


def test_empty_dashboard_is_ready_for_first_run(tmp_path):
    result = DashboardService(tmp_path / "empty.db").overview()

    assert result["run"] is None
    assert result["summary"]["universe"] == 0
    assert result["candidates"] == []
    assert result["next_action"]["key"] == "new"


def test_web_startup_prepares_and_verifies_database(tmp_path):
    db_path = tmp_path / "fresh" / "platform.db"

    result = prepare_database(db_path)

    assert result["status"] == "READY"
    assert result["file"] == "platform.db"
    assert result["migration_count"] >= 1


def test_health_endpoint_reports_frontend_backend_readiness(tmp_path):
    db_path = tmp_path / "health.db"
    prepare_database(db_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(db_path))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(
            f"http://127.0.0.1:{server.server_port}/api/health"
        ) as response:
            result = json.load(response)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result["status"] == "ok"
    assert result["service"] == "a-share-strategy-platform"
    assert result["database"]["status"] == "ready"
    assert result["strategies"]["count"] >= 1


def test_startup_reuses_an_existing_platform_process(tmp_path):
    db_path = tmp_path / "reuse.db"
    prepare_database(db_path)
    server, url = _bind_server(db_path, "127.0.0.1", 0)
    assert server is not None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        reused_server, reused_url = _bind_server(
            db_path, "127.0.0.1", server.server_port
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert reused_server is None
    assert reused_url == url


def test_dashboard_projects_formal_tier1_state(tmp_path):
    db_path = tmp_path / "dashboard.db"
    repository = Tier1Repository(db_path)
    repository.migrate_all()
    run_id = repository.begin_run(date(2026, 8, 10), Tier1Config())
    decision = evaluate_tier1(decision_input())
    repository.save_decision(run_id, decision)
    repository.finish_run(
        run_id,
        status="FINISHED",
        universe_size=1,
        price_dates=[date(2026, 8, 10)],
    )

    result = DashboardService(db_path).overview(run_id)

    assert result["run"]["run_id"] == run_id
    assert result["summary"]["universe"] == 1
    assert result["summary"]["stage_a_pass"] == 1
    assert result["candidates"][0]["screen_status"] == "PASS"
    assert result["candidates"][0]["stage_b_status"] == "待生成证据包"
    assert result["next_action"]["key"] == "export-tier2"
    assert result["run"]["progress"]["processed"] == 1
    assert result["run"]["progress"]["percent"] == 100.0


def test_running_dashboard_exposes_database_backed_progress(tmp_path):
    db_path = tmp_path / "progress.db"
    repository = Tier1Repository(db_path)
    repository.migrate_all()
    run_id = repository.begin_run(date(2026, 8, 10), Tier1Config())
    repository.set_run_universe_size(run_id, 10)
    repository.save_decision(run_id, evaluate_tier1(decision_input()))

    service = DashboardService(db_path)
    result = service.overview(run_id)
    running = service.running_runs()

    assert result["run"]["status"] == "RUNNING"
    assert result["run"]["progress"]["processed"] == 1
    assert result["run"]["progress"]["total"] == 10
    assert result["run"]["progress"]["percent"] == 10.0
    assert running[0]["run_id"] == run_id


def test_running_dashboard_surfaces_source_degradation(tmp_path):
    db_path = tmp_path / "source-health.db"
    repository = Tier1Repository(db_path)
    repository.migrate_all()
    run_id = repository.begin_run(date(2026, 8, 10), Tier1Config())
    repository.set_run_universe_size(run_id, 10)
    repository.save_observation(
        run_id,
        "000001",
        "market",
        DataEnvelope(
            status=FetchStatus.ERROR,
            data=None,
            provider="AKShare",
            endpoint="market",
            request={"symbol": "000001"},
            error_type="ConnectionError",
            error_message="connection reset by peer",
        ),
    )

    health = DashboardService(db_path).running_runs()[0]["progress"]["source_health"]

    assert health["status"] == "NETWORK_ISSUE"
    assert health["recent_error_count"] == 1
    assert health["last_error"]["symbol"] == "000001"


def test_candidate_read_model_filters_sorts_and_paginates_server_side(tmp_path):
    db_path = tmp_path / "pagination.db"
    repository = Tier1Repository(db_path)
    repository.migrate_all()
    run_id = repository.begin_run(date(2026, 8, 10), Tier1Config())
    for index in range(125):
        decision = evaluate_tier1(decision_input())
        decision.symbol = f"{index:06d}"
        decision.stock_name = f"测试公司{index:03d}"
        decision.selected_pe_ttm = float(index)
        repository.save_decision(run_id, decision)

    page = DashboardService(db_path).candidates_page(
        run_id,
        page=2,
        page_size=20,
        query="测试公司",
        filters={"pe": "GTE30"},
        sort_key="pe_ttm",
        sort_direction="desc",
    )

    assert page["total"] == 95
    assert page["pages"] == 5
    assert len(page["items"]) == 20
    assert page["items"][0]["pe_ttm"] == 104.0
    assert page["items"][-1]["pe_ttm"] == 85.0


def test_tier2_assessment_view_exposes_research_but_hides_local_evidence_paths():
    payload = {
        "schema_version": "tier2-ai-v1.1",
        "ai_provider": "provider",
        "ai_model": "model",
        "recommendation": "REVIEW",
        "dimensions": [
            {
                "dimension": "earnings_quality",
                "verdict": "WARN",
                "confidence": 0.82,
                "facts": ["经营现金流为正"],
                "inferences": ["现金转化尚可"],
                "counter_evidence": ["应收账款上升"],
                "reasoning_summary": "仍需跟踪",
                "falsification_conditions": ["现金流转负"],
                "sources": [
                    {
                        "title": "年度报告",
                        "publisher": "测试公司",
                        "date": "2026-03-28",
                        "page_or_section": "现金流量表",
                        "snapshot_path": "D:/private/report.pdf",
                        "content_sha256": "a" * 64,
                        "evidence_excerpt": "不应发送到浏览器",
                    }
                ],
            }
        ],
        "scenario_analysis": [{"scenario": "BASE", "value_per_share": 16.68}],
        "overall_reasoning": "当前接近合理价值",
        "overall_counter_evidence": ["净现金较高"],
        "falsification_conditions": ["销量持续下降"],
    }

    result = _tier2_assessment_view(json.dumps(payload, ensure_ascii=False))

    assert result["overall_reasoning"] == "当前接近合理价值"
    assert result["dimensions"][0]["facts"] == ["经营现金流为正"]
    assert result["scenario_analysis"][0]["value_per_share"] == 16.68
    source = result["dimensions"][0]["sources"][0]
    assert source == {
        "title": "年度报告",
        "publisher": "测试公司",
        "date": "2026-03-28",
        "page_or_section": "现金流量表",
    }


def test_market_workflow_starts_without_explicit_symbols(tmp_path):
    class RecordingJobs:
        def __init__(self):
            self.command = None

        def start(self, command, label):
            self.command = command
            return {"job_id": "market-job", "label": label, "status": "RUNNING"}

        def list(self):
            return []

    jobs = RecordingJobs()
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), build_handler(tmp_path / "web.db", jobs)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/workflows",
            data=json.dumps(
                {"scope": "market", "as_of": "2026-08-10", "symbols": ""}
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            payload = json.loads(response.read())

        assert response.status == 202
        assert payload["job"]["job_id"] == "market-job"
        assert "--symbols" not in jobs.command
        assert "全市场" in payload["job"]["label"]
    finally:
        server.shutdown()
        server.server_close()


def test_resume_endpoint_dispatches_controlled_cli_job(tmp_path):
    class RecordingJobs:
        def __init__(self):
            self.command = None

        def start(self, command, label):
            self.command = command
            return {"job_id": "resume-job", "label": label, "status": "RUNNING"}

        def list(self):
            return []

    jobs = RecordingJobs()
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), build_handler(tmp_path / "web.db", jobs)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/actions/resume-tier1",
            data=json.dumps({"run_id": "run-1"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            payload = json.loads(response.read())

        assert response.status == 202
        assert payload["job"]["job_id"] == "resume-job"
        assert "resume-tier1" in jobs.command
        assert jobs.command[jobs.command.index("--run-id") + 1] == "run-1"
    finally:
        server.shutdown()
        server.server_close()
