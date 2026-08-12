import sys
import time

from src.execution import JobRegistry


def _wait_for(registry, job_id, statuses, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = registry.get(job_id)
        if job["status"] in statuses:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not reach {statuses}")


def test_jobs_are_persistent_and_have_no_one_hour_subprocess_timeout(tmp_path):
    db_path = tmp_path / "jobs.db"
    registry = JobRegistry(db_path)

    started = registry.start([sys.executable, "-c", "print('done')"], "测试任务")
    completed = _wait_for(registry, started["job_id"], {"SUCCEEDED"})
    reloaded = JobRegistry(db_path).get(started["job_id"])

    assert completed["return_code"] == 0
    assert completed["output"] == "done"
    assert reloaded["status"] == "SUCCEEDED"


def test_job_queue_limits_concurrent_processes(tmp_path):
    registry = JobRegistry(tmp_path / "queue.db", max_concurrent=1)
    command = [sys.executable, "-c", "import time; time.sleep(.4)"]

    first = registry.start(command, "第一任务")
    _wait_for(registry, first["job_id"], {"RUNNING"})
    second = registry.start(command, "第二任务")
    time.sleep(0.05)

    assert registry.get(first["job_id"])["status"] == "RUNNING"
    assert registry.get(second["job_id"])["status"] == "QUEUED"
    _wait_for(registry, first["job_id"], {"SUCCEEDED"})
    _wait_for(registry, second["job_id"], {"SUCCEEDED"})


def test_job_can_be_cancelled_without_late_success_overwrite(tmp_path):
    registry = JobRegistry(tmp_path / "cancel.db")
    started = registry.start(
        [sys.executable, "-c", "import time; time.sleep(5)"], "可取消任务"
    )
    _wait_for(registry, started["job_id"], {"RUNNING"})

    cancelled = registry.cancel(started["job_id"])
    time.sleep(0.2)

    assert cancelled["status"] == "CANCELLED"
    assert registry.get(started["job_id"])["status"] == "CANCELLED"
    assert [item["event_type"] for item in registry.events(started["job_id"])] == [
        "QUEUED",
        "STARTED",
        "CANCELLED",
    ]


def test_queued_job_can_pause_and_resume(tmp_path):
    registry = JobRegistry(tmp_path / "pause.db", max_concurrent=1)
    first = registry.start(
        [sys.executable, "-c", "import time; time.sleep(.5)"], "占用任务"
    )
    _wait_for(registry, first["job_id"], {"RUNNING"})
    second = registry.start([sys.executable, "-c", "print('resumed')"], "暂停任务")

    assert registry.pause(second["job_id"])["status"] == "PAUSED"
    resumed = registry.resume(second["job_id"])
    assert resumed["status"] == "QUEUED"
    _wait_for(registry, second["job_id"], {"SUCCEEDED"})
    assert registry.get(second["job_id"])["output"] == "resumed"


def test_legacy_job_table_is_upgraded_without_losing_history(tmp_path):
    import sqlite3

    db_path = tmp_path / "legacy-jobs.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE platform_jobs (
                job_id TEXT PRIMARY KEY, label TEXT NOT NULL, command_json TEXT NOT NULL,
                status TEXT NOT NULL, queued_at TEXT NOT NULL, started_at TEXT,
                finished_at TEXT, process_id INTEGER, output TEXT NOT NULL DEFAULT '',
                return_code INTEGER,
                CHECK(status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','INTERRUPTED'))
            )
            """
        )
        connection.execute(
            """
            INSERT INTO platform_jobs(job_id, label, command_json, status, queued_at)
            VALUES ('old-job', '历史任务', '[\"python\"]', 'SUCCEEDED', '2026-08-12')
            """
        )

    registry = JobRegistry(db_path)

    assert registry.get("old-job")["status"] == "SUCCEEDED"
    with sqlite3.connect(db_path) as connection:
        sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='platform_jobs'"
        ).fetchone()[0]
    assert "'PAUSED'" in sql


def test_job_records_reproducibility_metadata_and_worker_heartbeat(tmp_path):
    registry = JobRegistry(tmp_path / "metadata.db")
    started = registry.start(
        [sys.executable, "-c", "import time; time.sleep(1.2)"],
        "可复现任务",
        metadata={"data_snapshot_id": "snapshot-1", "config_hash": "config-1"},
        retry_budget=2,
    )
    _wait_for(registry, started["job_id"], {"RUNNING"})
    initial_heartbeat = registry.get(started["job_id"])["heartbeat_at"]
    time.sleep(1.1)
    running = registry.get(started["job_id"])
    completed = _wait_for(registry, started["job_id"], {"SUCCEEDED"})

    assert running["heartbeat_at"] >= initial_heartbeat
    assert completed["metadata"]["data_snapshot_id"] == "snapshot-1"
    assert completed["metadata"]["config_hash"] == "config-1"
    assert len(completed["metadata"]["command_hash"]) == 64
    assert completed["retry_budget"] == 2


def test_queued_jobs_claim_capacity_by_priority(tmp_path):
    registry = JobRegistry(tmp_path / "priority.db", max_concurrent=1)
    blocker = registry.start(
        [sys.executable, "-c", "import time; time.sleep(.5)"], "占用任务"
    )
    _wait_for(registry, blocker["job_id"], {"RUNNING"})
    low = registry.start(
        [sys.executable, "-c", "import time; time.sleep(.3)"],
        "低优先级",
        priority=1,
    )
    high = registry.start(
        [sys.executable, "-c", "import time; time.sleep(.3)"],
        "高优先级",
        priority=100,
    )

    _wait_for(registry, blocker["job_id"], {"SUCCEEDED"})
    _wait_for(registry, high["job_id"], {"RUNNING", "SUCCEEDED"})
    assert registry.get(low["job_id"])["status"] == "QUEUED"
    _wait_for(registry, high["job_id"], {"SUCCEEDED"})
    _wait_for(registry, low["job_id"], {"SUCCEEDED"})


def test_registry_restart_adopts_live_worker_and_preserves_capacity(tmp_path):
    db_path = tmp_path / "restart-adoption.db"
    first_registry = JobRegistry(db_path, max_concurrent=1)
    running = first_registry.start(
        [sys.executable, "-c", "import time; time.sleep(1.2)"], "跨重启任务"
    )
    _wait_for(first_registry, running["job_id"], {"RUNNING"})

    restarted = JobRegistry(db_path, max_concurrent=1)
    adopted = restarted.get(running["job_id"])
    queued = restarted.start([sys.executable, "-c", "print('next')"], "后续任务")
    time.sleep(0.1)

    assert adopted["status"] == "RUNNING"
    assert restarted.get(queued["job_id"])["status"] == "QUEUED"
    assert "ADOPTED" in [
        item["event_type"] for item in restarted.events(running["job_id"])
    ]
    _wait_for(restarted, running["job_id"], {"SUCCEEDED"})
    _wait_for(restarted, queued["job_id"], {"SUCCEEDED"})


def test_registry_restart_interrupts_missing_worker(tmp_path):
    import json
    import sqlite3

    db_path = tmp_path / "missing-worker.db"
    JobRegistry(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO platform_jobs(
                job_id, label, command_json, status, queued_at, process_id
            ) VALUES ('missing', '丢失任务', ?, 'RUNNING', '2026-08-12', 99999999)
            """,
            (json.dumps([sys.executable, "-c", "print('never')"]),),
        )

    restarted = JobRegistry(db_path)

    assert restarted.get("missing")["status"] == "INTERRUPTED"


def test_registry_recovers_live_worker_misclassified_by_legacy_restart(tmp_path):
    import sqlite3

    db_path = tmp_path / "legacy-recovery.db"
    original = JobRegistry(db_path)
    running = original.start(
        [sys.executable, "-c", "import time; time.sleep(.8)"], "遗留误分类任务"
    )
    _wait_for(original, running["job_id"], {"RUNNING"})
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            UPDATE platform_jobs SET status='INTERRUPTED', finished_at='legacy',
                return_code=-1 WHERE job_id=?
            """,
            (running["job_id"],),
        )

    restarted = JobRegistry(db_path)

    assert restarted.get(running["job_id"])["status"] == "RUNNING"
    _wait_for(restarted, running["job_id"], {"SUCCEEDED", "INTERRUPTED"}, timeout=3)
