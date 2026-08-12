from __future__ import annotations

from datetime import date

import pytest

from src.strategies.golden_pit.config import Tier1Config
from src.strategies.golden_pit.module import GoldenPitStrategy
from src.strategies.golden_pit.persistence.tier1_repository import Tier1Repository
from src.strategies.golden_pit.presentation import GoldenPitReadModel


def _running_run(repository: Tier1Repository) -> tuple[str, str]:
    run_id = repository.begin_run(date(2026, 8, 12), Tier1Config())
    token = repository.acquire_run_lease(run_id, allow_recent_activity=True)
    return run_id, token


def test_pause_fences_old_worker_and_manual_resume_reopens_run(tmp_path):
    db_path = tmp_path / "run-controls.db"
    repository = Tier1Repository(db_path)
    run_id, old_token = _running_run(repository)

    result = repository.control_run(
        run_id,
        "PAUSE",
        actor="operator-a",
        reason="planned pause",
    )

    assert result["status"] == "PAUSED"
    assert repository.run_record(run_id)["status"] == "PAUSED"
    with pytest.raises(ValueError, match="租约已失效"):
        repository.heartbeat_run_lease(run_id, old_token)

    repository.mark_run_interrupted(run_id, RuntimeError("stale worker exit"))
    assert repository.run_record(run_id)["status"] == "PAUSED"
    overview = GoldenPitReadModel(db_path).overview(run_id)
    assert overview["runs"][0]["manual_control"]["action"] == "PAUSE"
    assert overview["runs"][0]["manual_control"]["actor"] == "operator-a"

    repository.prepare_manual_resume(
        run_id,
        actor="operator-b",
        reason="continue screening",
    )
    assert repository.run_record(run_id)["status"] == "INTERRUPTED"
    with repository.connect() as connection:
        actions = [
            row[0]
            for row in connection.execute(
                """
                SELECT action FROM screening_run_control_events
                WHERE run_id=? ORDER BY created_at
                """,
                (run_id,),
            ).fetchall()
        ]
        assert actions == ["PAUSE", "RESUME"]
        assert connection.execute(
            "SELECT 1 FROM screening_run_leases WHERE run_id=?", (run_id,)
        ).fetchone() is None

    new_token = repository.acquire_run_lease(run_id, allow_recent_activity=True)
    assert new_token != old_token
    assert repository.run_record(run_id)["status"] == "RUNNING"
    repository.release_run_lease(run_id, new_token)


def test_stopped_run_is_terminal_and_cannot_be_resumed(tmp_path):
    repository = Tier1Repository(tmp_path / "stopped-run.db")
    run_id, old_token = _running_run(repository)

    repository.control_run(run_id, "PAUSE", actor="operator-a")
    result = repository.control_run(run_id, "STOP", actor="operator-a")

    assert result["status"] == "CANCELLED"
    assert repository.run_record(run_id)["status"] == "CANCELLED"
    with pytest.raises(ValueError, match="租约已失效"):
        repository.heartbeat_run_lease(run_id, old_token)
    with pytest.raises(ValueError, match="只有手动暂停"):
        repository.prepare_manual_resume(run_id, actor="operator-a")
    with pytest.raises(ValueError, match="活动工作进程"):
        repository.acquire_run_lease(run_id, allow_recent_activity=True)


def test_strategy_actions_expose_pause_and_manual_resume(tmp_path):
    db_path = tmp_path / "strategy-actions.db"
    repository = Tier1Repository(db_path)
    run_id, _ = _running_run(repository)
    strategy = GoldenPitStrategy(db_path)

    paused = strategy.handle_action(
        "pause-run", {"run_id": run_id, "actor": "web-operator"}
    )

    assert paused.kind == "result"
    assert paused.payload["run"]["status"] == "PAUSED"
    assert paused.payload["run"]["worker_terminated"] is False
    assert "Web 服务自身" in paused.payload["run"]["worker_warning"]

    resumed = strategy.handle_action(
        "resume-run", {"run_id": run_id, "actor": "web-operator"}
    )

    assert resumed.kind == "job"
    assert "resume-tier1" in resumed.command
    assert run_id in resumed.command
    assert repository.run_record(run_id)["status"] == "INTERRUPTED"
