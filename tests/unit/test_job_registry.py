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
