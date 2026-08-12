"""Persistent, concurrency-bounded background process execution."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = PROJECT_ROOT / "data" / "db" / "platform_jobs.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobRegistry:
    """SQLite-backed local queue that survives page refreshes and limits workers."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        max_concurrent: int = 1,
        max_pending: int = 20,
    ) -> None:
        if max_concurrent < 1 or max_pending < 1:
            raise ValueError("任务并发数和排队上限必须为正数")
        self.db_path = Path(db_path or DEFAULT_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_concurrent = max_concurrent
        self.max_pending = max_pending
        queued = self._initialize()
        for job_id, command in queued:
            self._start_worker(job_id, command)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> list[tuple[str, list[str]]]:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS platform_jobs (
                    job_id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    command_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    queued_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    process_id INTEGER,
                    output TEXT NOT NULL DEFAULT '',
                    return_code INTEGER,
                    CHECK(status IN (
                        'QUEUED','RUNNING','SUCCEEDED','FAILED','INTERRUPTED'
                    ))
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_platform_jobs_status_queued
                ON platform_jobs(status, queued_at)
                """
            )
            connection.execute(
                """
                UPDATE platform_jobs
                SET status='INTERRUPTED', finished_at=?, return_code=-1,
                    output=CASE WHEN output='' THEN ? ELSE output || char(10) || ? END
                WHERE status='RUNNING'
                """,
                (
                    _now(),
                    "任务执行器重启；正式筛选可从运行记录断点续跑。",
                    "任务执行器重启；正式筛选可从运行记录断点续跑。",
                ),
            )
            queued_rows = connection.execute(
                """
                SELECT job_id, command_json FROM platform_jobs
                WHERE status='QUEUED' ORDER BY queued_at
                """
            ).fetchall()
        return [
            (str(row["job_id"]), list(json.loads(row["command_json"])))
            for row in queued_rows
        ]

    def start(self, command: list[str], label: str) -> dict[str, Any]:
        if not command:
            raise ValueError("后台任务命令不能为空")
        job_id = str(uuid.uuid4())
        queued_at = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            pending = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM platform_jobs
                    WHERE status IN ('QUEUED','RUNNING')
                    """
                ).fetchone()[0]
            )
            if pending >= self.max_pending:
                raise ValueError("后台任务队列已满，请等待现有任务完成")
            connection.execute(
                """
                INSERT INTO platform_jobs(
                    job_id, label, command_json, status, queued_at
                ) VALUES (?, ?, ?, 'QUEUED', ?)
                """,
                (job_id, label, json.dumps(command, ensure_ascii=False), queued_at),
            )
        self._start_worker(job_id, list(command))
        return self.get(job_id)

    def _start_worker(self, job_id: str, command: list[str]) -> None:
        thread = threading.Thread(
            target=self._run,
            args=(job_id, command),
            name=f"platform-job-{job_id[:8]}",
            daemon=True,
        )
        thread.start()

    def _claim(self, job_id: str) -> bool:
        while True:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT status FROM platform_jobs WHERE job_id=?", (job_id,)
                ).fetchone()
                if row is None or str(row["status"]) != "QUEUED":
                    return False
                running = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM platform_jobs WHERE status='RUNNING'"
                    ).fetchone()[0]
                )
                if running < self.max_concurrent:
                    connection.execute(
                        """
                        UPDATE platform_jobs SET status='RUNNING', started_at=?
                        WHERE job_id=? AND status='QUEUED'
                        """,
                        (_now(), job_id),
                    )
                    return True
            time.sleep(0.25)

    def _run(self, job_id: str, command: list[str]) -> None:
        if not self._claim(job_id):
            return
        try:
            process = subprocess.Popen(
                command,
                cwd=PROJECT_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            with self._connect() as connection:
                connection.execute(
                    "UPDATE platform_jobs SET process_id=? WHERE job_id=?",
                    (process.pid, job_id),
                )
            stdout, stderr = process.communicate()
            output = (stdout + "\n" + stderr).strip()[-20_000:]
            status = "SUCCEEDED" if process.returncode == 0 else "FAILED"
            return_code = process.returncode
        except Exception as exc:  # pragma: no cover - defensive process boundary
            output = f"{type(exc).__name__}: {exc}"
            status = "FAILED"
            return_code = -1
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE platform_jobs
                SET status=?, finished_at=?, output=?, return_code=?
                WHERE job_id=?
                """,
                (status, _now(), output, return_code, job_id),
            )

    def get(self, job_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT job_id, label, status,
                       COALESCE(started_at, queued_at) AS started_at,
                       finished_at, output, return_code, process_id
                FROM platform_jobs WHERE job_id=?
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"未知后台任务: {job_id}")
        return dict(row)

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT job_id, label, status,
                       COALESCE(started_at, queued_at) AS started_at,
                       finished_at, output, return_code, process_id
                FROM platform_jobs ORDER BY queued_at DESC LIMIT 20
                """
            ).fetchall()
        return [dict(row) for row in rows]
