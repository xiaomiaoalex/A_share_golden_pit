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

import psutil

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
        self._adopted_processes: dict[str, psutil.Process] = {}
        self._process_lock = threading.Lock()
        queued, adopted = self._initialize()
        for job_id, process in adopted:
            self._adopted_processes[job_id] = process
            self._start_adopted_monitor(job_id, process)
        for job_id, command in queued:
            self._start_worker(job_id, command)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(
        self,
    ) -> tuple[list[tuple[str, list[str]]], list[tuple[str, psutil.Process]]]:
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
            adopted: list[tuple[str, psutil.Process]] = []
            running_rows = connection.execute(
                """
                SELECT job_id, command_json, process_id, status, return_code
                FROM platform_jobs
                WHERE status='RUNNING'
                   OR (status='INTERRUPTED' AND return_code=-1)
                """
            ).fetchall()
            for row in running_rows:
                command = list(json.loads(row["command_json"]))
                process = self._matching_process(row["process_id"], command)
                if process is not None:
                    if str(row["status"]) == "INTERRUPTED":
                        connection.execute(
                            """
                            UPDATE platform_jobs SET status='RUNNING', finished_at=NULL,
                                return_code=NULL, heartbeat_at=? WHERE job_id=?
                            """,
                            (_now(), row["job_id"]),
                        )
                    adopted.append((str(row["job_id"]), process))
                    self._event(
                        connection,
                        str(row["job_id"]),
                        "ADOPTED",
                        {"process_id": process.pid},
                    )
                    continue
                if str(row["status"]) != "RUNNING":
                    continue
                message = "任务执行器重启且原 Worker 已不存在；可从运行记录断点续跑。"
                connection.execute(
                    """
                    UPDATE platform_jobs
                    SET status='INTERRUPTED', finished_at=?, return_code=-1,
                        output=CASE WHEN output='' THEN ? ELSE output || char(10) || ? END
                    WHERE job_id=? AND status='RUNNING'
                    """,
                    (_now(), message, message, row["job_id"]),
                )
                self._event(
                    connection, str(row["job_id"]), "INTERRUPTED", {"reason": message}
                )
            queued_rows = connection.execute(
                """
                SELECT job_id, command_json FROM platform_jobs
                WHERE status='QUEUED' ORDER BY queued_at
                """
            ).fetchall()
        queued = [
            (str(row["job_id"]), list(json.loads(row["command_json"])))
            for row in queued_rows
        ]
        return queued, adopted

    @staticmethod
    def _matching_process(
        process_id: Any, command: list[str]
    ) -> psutil.Process | None:
        """Return a live process only when the persisted command still matches."""
        if not process_id:
            return None
        try:
            process = psutil.Process(int(process_id))
            if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
                return None
            actual = process.cmdline()
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError, OSError):
            return None
        if len(actual) != len(command):
            return None

        def normalize(value: str, *, executable: bool = False) -> str:
            if executable:
                try:
                    return str(Path(value).resolve()).casefold()
                except OSError:
                    pass
            return value.casefold() if os.name == "nt" else value

        return process if all(
            normalize(current, executable=index == 0)
            == normalize(expected, executable=index == 0)
            for index, (current, expected) in enumerate(zip(actual, command))
        ) else None

    def _start_adopted_monitor(
        self, job_id: str, process: psutil.Process
    ) -> None:
        threading.Thread(
            target=self._monitor_adopted,
            args=(job_id, process),
            name=f"platform-adopted-{job_id[:8]}",
            daemon=True,
        ).start()

    def _monitor_adopted(self, job_id: str, process: psutil.Process) -> None:
        """Keep an inherited Worker visible and capacity-accounted until it exits."""
        while True:
            try:
                alive = process.is_running() and process.status() != psutil.STATUS_ZOMBIE
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                alive = False
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT status FROM platform_jobs WHERE job_id=?", (job_id,)
                ).fetchone()
                if row is None or str(row["status"]) != "RUNNING":
                    break
                if not alive:
                    message = "重启后接管的 Worker 已退出，无法可靠获取退出码；请核对策略运行记录。"
                    connection.execute(
                        """
                        UPDATE platform_jobs SET status='INTERRUPTED', finished_at=?,
                            return_code=-1,
                            output=CASE WHEN output='' THEN ? ELSE output || char(10) || ? END
                        WHERE job_id=? AND status='RUNNING'
                        """,
                        (_now(), message, message, job_id),
                    )
                    self._event(
                        connection, job_id, "INTERRUPTED", {"reason": message}
                    )
                    break
                connection.execute(
                    "UPDATE platform_jobs SET heartbeat_at=? WHERE job_id=?",
                    (_now(), job_id),
                )
            time.sleep(1.0)
        with self._process_lock:
            self._adopted_processes.pop(job_id, None)

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
            adopted = self._adopted_processes.get(job_id)
        if process is not None and process.poll() is None:
            self._terminate_process_tree(process.pid)
        if adopted is not None:
            self._terminate_process_tree(adopted.pid)
        return self.get(job_id)

    @staticmethod
    def _terminate_process_tree(process_id: int) -> None:
        """Synchronously stop a managed process tree before capacity is reused."""
        try:
            parent = psutil.Process(process_id)
            processes = [*parent.children(recursive=True), parent]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return
        for process in processes:
            try:
                process.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(processes, timeout=5)
        for process in alive:
            try:
                process.kill()
            except psutil.NoSuchProcess:
                pass
        if alive:
            psutil.wait_procs(alive, timeout=3)

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
