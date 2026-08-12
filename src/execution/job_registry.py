"""Persistent, concurrency-bounded background process execution."""

from __future__ import annotations

import hashlib
import json
import os
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
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._process_lock = threading.Lock()
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
            existing = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='platform_jobs'"
            ).fetchone()
            if existing is not None and "'PAUSED'" not in str(existing[0]):
                self._upgrade_legacy_status_constraint(connection)
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
                        'QUEUED','RUNNING','PAUSED','CANCELLED',
                        'SUCCEEDED','FAILED','INTERRUPTED'
                    ))
                )
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(platform_jobs)")
            }
            if "priority" not in columns:
                connection.execute(
                    "ALTER TABLE platform_jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0"
                )
            if "heartbeat_at" not in columns:
                connection.execute("ALTER TABLE platform_jobs ADD COLUMN heartbeat_at TEXT")
            if "metadata_json" not in columns:
                connection.execute(
                    "ALTER TABLE platform_jobs ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'"
                )
            if "retry_budget" not in columns:
                connection.execute(
                    "ALTER TABLE platform_jobs ADD COLUMN retry_budget INTEGER NOT NULL DEFAULT 0"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS platform_job_events (
                    event_id TEXT PRIMARY KEY, job_id TEXT NOT NULL,
                    event_type TEXT NOT NULL, payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES platform_jobs(job_id)
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

    @staticmethod
    def _upgrade_legacy_status_constraint(connection: sqlite3.Connection) -> None:
        """Rebuild the local queue table because SQLite cannot alter CHECK clauses."""
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("ALTER TABLE platform_jobs RENAME TO platform_jobs_legacy")
        connection.execute(
            """
            CREATE TABLE platform_jobs (
                job_id TEXT PRIMARY KEY, label TEXT NOT NULL,
                command_json TEXT NOT NULL, status TEXT NOT NULL,
                queued_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
                process_id INTEGER, output TEXT NOT NULL DEFAULT '',
                return_code INTEGER, priority INTEGER NOT NULL DEFAULT 0,
                heartbeat_at TEXT,
                CHECK(status IN ('QUEUED','RUNNING','PAUSED','CANCELLED',
                    'SUCCEEDED','FAILED','INTERRUPTED'))
            )
            """
        )
        legacy_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(platform_jobs_legacy)")
        }
        priority = "priority" if "priority" in legacy_columns else "0"
        heartbeat = "heartbeat_at" if "heartbeat_at" in legacy_columns else "NULL"
        connection.execute(
            f"""
            INSERT INTO platform_jobs(
                job_id, label, command_json, status, queued_at, started_at,
                finished_at, process_id, output, return_code, priority, heartbeat_at
            )
            SELECT job_id, label, command_json, status, queued_at, started_at,
                   finished_at, process_id, output, return_code, {priority}, {heartbeat}
            FROM platform_jobs_legacy
            """  # noqa: S608 - fragments are selected from fixed identifiers
        )
        connection.execute("DROP TABLE platform_jobs_legacy")
        connection.execute("PRAGMA foreign_keys=ON")

    def start(
        self,
        command: list[str],
        label: str,
        *,
        priority: int = 0,
        metadata: dict[str, Any] | None = None,
        retry_budget: int = 0,
    ) -> dict[str, Any]:
        if not command:
            raise ValueError("后台任务命令不能为空")
        job_id = str(uuid.uuid4())
        queued_at = _now()
        reproducibility = {
            "git_sha": os.environ.get("PLATFORM_RELEASE_SHA")
            or os.environ.get("GITHUB_SHA")
            or "working-tree",
            "command_hash": hashlib.sha256(
                json.dumps(command, ensure_ascii=False).encode()
            ).hexdigest(),
            "random_seed": 0,
            **(metadata or {}),
        }
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
                    job_id, label, command_json, status, queued_at, priority,
                    metadata_json, retry_budget
                ) VALUES (?, ?, ?, 'QUEUED', ?, ?, ?, ?)
                """,
                (
                    job_id,
                    label,
                    json.dumps(command, ensure_ascii=False),
                    queued_at,
                    priority,
                    json.dumps(reproducibility, ensure_ascii=False, sort_keys=True),
                    retry_budget,
                ),
            )
            self._event(
                connection,
                job_id,
                "QUEUED",
                {"priority": priority, "reproducibility": reproducibility},
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
                    next_job = connection.execute(
                        """
                        SELECT job_id FROM platform_jobs
                        WHERE status='QUEUED'
                        ORDER BY priority DESC, queued_at, job_id
                        LIMIT 1
                        """
                    ).fetchone()
                    if next_job is not None and str(next_job["job_id"]) == job_id:
                        connection.execute(
                            """
                            UPDATE platform_jobs
                            SET status='RUNNING', started_at=?, heartbeat_at=?
                            WHERE job_id=? AND status='QUEUED'
                            """,
                            (_now(), _now(), job_id),
                        )
                        self._event(connection, job_id, "STARTED", {})
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
            with self._process_lock:
                self._processes[job_id] = process
            with self._connect() as connection:
                connection.execute(
                    "UPDATE platform_jobs SET process_id=? WHERE job_id=?",
                    (process.pid, job_id),
                )
            while True:
                try:
                    stdout, stderr = process.communicate(timeout=1.0)
                    break
                except subprocess.TimeoutExpired:
                    with self._connect() as connection:
                        connection.execute(
                            """
                            UPDATE platform_jobs SET heartbeat_at=?
                            WHERE job_id=? AND status='RUNNING'
                            """,
                            (_now(), job_id),
                        )
            output = (stdout + "\n" + stderr).strip()[-20_000:]
            status = "SUCCEEDED" if process.returncode == 0 else "FAILED"
            return_code = process.returncode
        except Exception as exc:  # pragma: no cover - defensive process boundary
            output = f"{type(exc).__name__}: {exc}"
            status = "FAILED"
            return_code = -1
        finally:
            with self._process_lock:
                self._processes.pop(job_id, None)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE platform_jobs
                SET status=?, finished_at=?, output=?, return_code=?
                WHERE job_id=? AND status='RUNNING'
                """,
                (status, _now(), output, return_code, job_id),
            )
            if cursor.rowcount == 1:
                self._event(connection, job_id, status, {"return_code": return_code})

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        job_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO platform_job_events(
                event_id, job_id, event_type, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), job_id, event_type, json.dumps(payload), _now()),
        )

    def cancel(self, job_id: str) -> dict[str, Any]:
        return self._stop(job_id, "CANCELLED")

    def pause(self, job_id: str) -> dict[str, Any]:
        return self._stop(job_id, "PAUSED")

    def _stop(self, job_id: str, target: str) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE platform_jobs SET status=?, finished_at=?
                WHERE job_id=? AND status IN ('QUEUED','RUNNING')
                """,
                (target, _now(), job_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("任务不存在或当前状态不可控制")
            self._event(connection, job_id, target, {})
        with self._process_lock:
            process = self._processes.get(job_id)
        if process is not None and process.poll() is None:
            process.terminate()
        return self.get(job_id)

    def resume(self, job_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT command_json FROM platform_jobs WHERE job_id=? AND status='PAUSED'",
                (job_id,),
            ).fetchone()
            if row is None:
                raise ValueError("只有已暂停任务可以恢复")
            connection.execute(
                """
                UPDATE platform_jobs SET status='QUEUED', started_at=NULL,
                    finished_at=NULL, process_id=NULL, return_code=NULL
                WHERE job_id=?
                """,
                (job_id,),
            )
            self._event(connection, job_id, "RESUMED", {})
            command = list(json.loads(row["command_json"]))
        self._start_worker(job_id, command)
        return self.get(job_id)

    def events(self, job_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_type, payload_json, created_at
                FROM platform_job_events WHERE job_id=? ORDER BY created_at
                """,
                (job_id,),
            ).fetchall()
        return [
            {
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def get(self, job_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT job_id, label, status,
                       COALESCE(started_at, queued_at) AS started_at,
                       finished_at, output, return_code, process_id, priority,
                       heartbeat_at, metadata_json, retry_budget
                FROM platform_jobs WHERE job_id=?
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"未知后台任务: {job_id}")
        result = dict(row)
        result["metadata"] = json.loads(result.pop("metadata_json"))
        return result

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT job_id, label, status,
                       COALESCE(started_at, queued_at) AS started_at,
                       finished_at, output, return_code, process_id, priority,
                       heartbeat_at, metadata_json, retry_budget
                FROM platform_jobs ORDER BY queued_at DESC LIMIT 20
                """
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json"))
            result.append(item)
        return result
