"""SQLite repository for Stage A Tier1 v2 data.

Stage A uses additive, versioned SQLite migrations and stores every run
independently.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional

from src.data.point_in_time.contracts import (
    DataEnvelope,
    DividendBundle,
    UniverseItem,
)
from src.data.quality.types import QualityAssessment
from src.strategies.golden_pit.config import Tier1Config
from src.strategies.golden_pit.quantitative_screening.contracts import (
    FinancialReportFact,
    QuarterlyMetric,
    RiskWarningStatus,
    Tier1Decision,
)
from src.strategies.golden_pit.quantitative_screening.metrics import DividendCalculation
from src.strategies.golden_pit.versioning import build_release_manifest

MIGRATIONS = (
    ("001_tier1_v2", "001_tier1_v2_up.sql", "Stage A strict Tier1 v2"),
    (
        "002_tier1_data_quality",
        "002_tier1_data_quality_up.sql",
        "Tier1 business data quality assessments",
    ),
    (
        "005_tier1_resume",
        "005_tier1_resume_up.sql",
        "Stage A resumable universe, attempts and worker leases",
    ),
    (
        "006_strategy_identity",
        "006_strategy_identity_up.sql",
        "Multi-strategy run ownership; historical runs belong to golden-pit",
    ),
    (
        "golden-pit:007_execution_integrity",
        "007_execution_integrity_up.sql",
        "Append-only decisions, release manifests and execution integrity",
    ),
)
MIGRATION_VERSION = MIGRATIONS[-1][0]

STAGE_B_MIGRATIONS = (
    (
        "003_tier2_human_ai",
        "003_tier2_human_ai_up.sql",
        "Stage B Tier2 human-AI evidence workflow",
    ),
)

STAGE_C_MIGRATIONS = (
    (
        "004_tier3_risk_filter",
        "004_tier3_risk_filter_up.sql",
        "Stage C industry-aware risk and value-trap filter",
    ),
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


class Tier1Repository:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.project_root = Path(__file__).resolve().parents[4]

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def migrate(self) -> None:
        self._apply_migrations(MIGRATIONS)

    def migrate_through_stage_b(self) -> None:
        self._apply_migrations(MIGRATIONS + STAGE_B_MIGRATIONS)

    def migrate_all(self) -> None:
        self._apply_migrations(MIGRATIONS + STAGE_B_MIGRATIONS + STAGE_C_MIGRATIONS)

    def _apply_migrations(self, migrations) -> None:
        with self._migration_lock():
            with self.connect() as connection:
                for version, filename, description in migrations:
                    applied = False
                    if self._table_exists(connection, "schema_migrations"):
                        applied = (
                            connection.execute(
                                "SELECT 1 FROM schema_migrations WHERE version=?",
                                (version,),
                            ).fetchone()
                            is not None
                        )
                    if applied:
                        continue
                    up_path = self.project_root / "scripts" / "migrations" / filename
                    escaped = tuple(
                        value.replace("'", "''")
                        for value in (version, datetime.now().isoformat(), description)
                    )
                    registration = (
                        "INSERT INTO schema_migrations(version, applied_at, description) "
                        f"VALUES ('{escaped[0]}', '{escaped[1]}', '{escaped[2]}');"
                    )
                    self._execute_scripts_atomically(
                        connection,
                        [up_path.read_text(encoding="utf-8"), registration],
                    )

    @contextmanager
    def _migration_lock(self, timeout_seconds: float = 30.0):
        """Serialize DDL across local worker and web processes."""
        lock_path = self.db_path.with_suffix(self.db_path.suffix + ".migration.lock")
        deadline = time.monotonic() + timeout_seconds
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(
                    lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                )
                os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
            except FileExistsError:
                try:
                    stale = time.time() - lock_path.stat().st_mtime > 300
                except FileNotFoundError:
                    continue
                if stale:
                    try:
                        lock_path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"等待数据库迁移锁超时: {lock_path}")
                time.sleep(0.1)
        try:
            yield
        finally:
            os.close(descriptor)
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _execute_scripts_atomically(
        connection: sqlite3.Connection, scripts: list[str]
    ) -> None:
        body = "\n".join(scripts)
        try:
            connection.executescript(f"BEGIN IMMEDIATE;\n{body}\nCOMMIT;")
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise

    def rollback_stage_a(self) -> None:
        strategy_identity_down = (
            self.project_root
            / "scripts"
            / "migrations"
            / "006_strategy_identity_down.sql"
        )
        resume_down = (
            self.project_root / "scripts" / "migrations" / "005_tier1_resume_down.sql"
        )
        tier3_down = (
            self.project_root / "scripts" / "migrations" / "004_tier3_risk_filter_down.sql"
        )
        tier2_down = (
            self.project_root / "scripts" / "migrations" / "003_tier2_human_ai_down.sql"
        )
        quality_down = (
            self.project_root
            / "scripts"
            / "migrations"
            / "002_tier1_data_quality_down.sql"
        )
        down_path = (
            self.project_root / "scripts" / "migrations" / "001_tier1_v2_down.sql"
        )
        integrity_down = (
            self.project_root
            / "scripts"
            / "migrations"
            / "007_execution_integrity_down.sql"
        )
        with self.connect() as connection:
            self._execute_scripts_atomically(
                connection,
                [
                    integrity_down.read_text(encoding="utf-8"),
                    strategy_identity_down.read_text(encoding="utf-8"),
                    resume_down.read_text(encoding="utf-8"),
                    tier3_down.read_text(encoding="utf-8"),
                    tier2_down.read_text(encoding="utf-8"),
                    quality_down.read_text(encoding="utf-8"),
                    down_path.read_text(encoding="utf-8"),
                    "DELETE FROM schema_migrations WHERE version IN "
                    "('001_tier1_v2','002_tier1_data_quality',"
                    "'003_tier2_human_ai','004_tier3_risk_filter',"
                    "'005_tier1_resume','006_strategy_identity',"
                    "'golden-pit:007_execution_integrity');",
                ],
            )

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        return row is not None

    def begin_run(self, as_of_date: date, config: Tier1Config) -> str:
        self.migrate()
        run_id = str(uuid.uuid4())
        release_manifest = build_release_manifest(config)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO screening_runs(
                    run_id, strategy_id, as_of_date, calculation_version, config_json,
                    release_manifest_json, status, started_at
                ) VALUES (?, 'golden-pit', ?, ?, ?, ?, 'RUNNING', ?)
                """,
                (
                    run_id,
                    as_of_date.isoformat(),
                    config.calculation_version,
                    _json(config.to_dict()),
                    _json(release_manifest),
                    datetime.now().isoformat(),
                ),
            )
        return run_id

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        universe_size: int,
        price_dates: Iterable[date] = (),
        errors: Optional[list[str]] = None,
    ) -> None:
        dates = sorted(price_dates)
        quality_summary = self.quality_summary(run_id)
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE screening_runs
                SET status=?, finished_at=?, universe_size=?, price_date_min=?,
                    price_date_max=?, error_summary_json=?,
                    data_quality_summary_json=?
                WHERE run_id=?
                """,
                (
                    status,
                    datetime.now().isoformat(),
                    universe_size,
                    dates[0].isoformat() if dates else None,
                    dates[-1].isoformat() if dates else None,
                    _json(errors or []),
                    _json(quality_summary),
                    run_id,
                ),
            )

    def set_run_universe_size(self, run_id: str, universe_size: int) -> None:
        """Persist the final work-unit count before per-symbol processing starts."""
        if universe_size < 0:
            raise ValueError("universe_size不得为负数")
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE screening_runs SET universe_size=?
                WHERE run_id=? AND status='RUNNING'
                """,
                (universe_size, run_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"无法更新运行中的股票池规模: {run_id}")

    def save_run_universe(
        self,
        run_id: str,
        items: Iterable[UniverseItem],
        *,
        snapshot_source: str = "CAPTURED",
    ) -> str:
        """Persist an immutable, ordered universe used for exact resumption."""
        self.migrate()
        universe = list(items)
        canonical = [
            {
                "position": position,
                "symbol": item.symbol,
                "stock_name": item.name,
                "exchange": item.exchange,
            }
            for position, item in enumerate(universe, start=1)
        ]
        content = json.dumps(
            canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        now = datetime.now().isoformat()
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM screening_universe_snapshots WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["content_hash"]) != content_hash
                    or int(existing["item_count"]) != len(universe)
                ):
                    raise ValueError("已固化股票池与待写入股票池不一致，禁止覆盖")
                return content_hash
            run = connection.execute(
                "SELECT 1 FROM screening_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if run is None:
                raise ValueError(f"未知Tier1 run_id: {run_id}")
            connection.execute(
                """
                INSERT INTO screening_universe_snapshots(
                    run_id, content_hash, item_count, snapshot_source, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, content_hash, len(universe), snapshot_source, now),
            )
            connection.executemany(
                """
                INSERT INTO screening_run_universe(
                    run_id, symbol, stock_name, exchange, position, item_status,
                    attempt_count
                ) VALUES (?, ?, ?, ?, ?, 'PENDING', 0)
                """,
                [
                    (
                        run_id,
                        row["symbol"],
                        row["stock_name"],
                        row["exchange"],
                        row["position"],
                    )
                    for row in canonical
                ],
            )
            connection.execute(
                "UPDATE screening_runs SET universe_size=? WHERE run_id=?",
                (len(universe), run_id),
            )
        return content_hash

    def load_run_universe(self, run_id: str) -> list[UniverseItem]:
        self.migrate()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT symbol, stock_name, exchange FROM screening_run_universe
                WHERE run_id=? ORDER BY position
                """,
                (run_id,),
            ).fetchall()
        return [
            UniverseItem(
                symbol=str(row["symbol"]),
                name=str(row["stock_name"]),
                exchange=str(row["exchange"]),
            )
            for row in rows
        ]

    def has_run_universe(self, run_id: str) -> bool:
        self.migrate()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM screening_universe_snapshots WHERE run_id=?",
                (run_id,),
            ).fetchone()
        return row is not None

    def legacy_universe_size(self, run_id: str) -> int | None:
        """Return the recorded total used to validate a reconstructed legacy snapshot."""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT universe_size FROM screening_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"未知Tier1 run_id: {run_id}")
            if row["universe_size"] is not None:
                return int(row["universe_size"])
            observed = connection.execute(
                """
                SELECT MAX(row_count) FROM source_observations
                WHERE run_id=? AND field_group='universe'
                  AND fetch_status='SUCCESS'
                """,
                (run_id,),
            ).fetchone()[0]
        return int(observed) if observed is not None else None

    def backfill_run_universe_progress(self, run_id: str) -> None:
        """Mark already-decided legacy symbols complete after snapshot reconstruction."""
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE screening_run_universe
                SET item_status='COMPLETED', last_trigger='INITIAL',
                    attempt_count=CASE WHEN attempt_count=0 THEN 1 ELSE attempt_count END,
                    last_attempt_finished_at=(
                        SELECT d.created_at FROM tier1_decisions d
                        WHERE d.run_id=screening_run_universe.run_id
                          AND d.symbol=screening_run_universe.symbol
                    )
                WHERE run_id=? AND EXISTS (
                    SELECT 1 FROM tier1_decisions d
                    WHERE d.run_id=screening_run_universe.run_id
                      AND d.symbol=screening_run_universe.symbol
                )
                """,
                (run_id,),
            )

    def acquire_run_lease(
        self,
        run_id: str,
        *,
        allow_recent_activity: bool = False,
        lease_seconds: int = 120,
    ) -> str:
        """Acquire exclusive ownership and reject concurrent/still-live workers."""
        self.migrate()
        now = datetime.now()
        token = str(uuid.uuid4())
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                "SELECT status FROM screening_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if run is None:
                raise ValueError(f"未知Tier1 run_id: {run_id}")
            lease = connection.execute(
                "SELECT * FROM screening_run_leases WHERE run_id=?", (run_id,)
            ).fetchone()
            if lease is not None:
                expiry = datetime.fromisoformat(str(lease["lease_expires_at"]))
                if expiry > now:
                    raise ValueError("该运行已有活动工作进程，禁止并发续跑")
                connection.execute(
                    "DELETE FROM screening_run_leases WHERE run_id=?", (run_id,)
                )
            if not allow_recent_activity and str(run["status"]) == "RUNNING":
                recent = connection.execute(
                    """
                    SELECT MAX(event_at) FROM (
                        SELECT MAX(fetched_at) AS event_at FROM source_observations
                        WHERE run_id=?
                        UNION ALL
                        SELECT MAX(created_at) AS event_at FROM tier1_decisions
                        WHERE run_id=?
                    )
                    """,
                    (run_id, run_id),
                ).fetchone()[0]
                if recent:
                    latest = datetime.fromisoformat(str(recent))
                    if (now - latest).total_seconds() < lease_seconds:
                        raise ValueError("运行仍在产生数据，请等待其停止后再续跑")
            expiry = now + timedelta(seconds=lease_seconds)
            connection.execute(
                """
                INSERT INTO screening_run_leases(
                    run_id, worker_token, process_id, host_name, acquired_at,
                    heartbeat_at, lease_expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    token,
                    os.getpid(),
                    socket.gethostname(),
                    now.isoformat(),
                    now.isoformat(),
                    expiry.isoformat(),
                ),
            )
            connection.execute(
                """
                UPDATE tier1_item_attempts
                SET status='FAILED', finished_at=?, error_type='LEASE_EXPIRED',
                    error_message='前一工作进程在完成标的前中断'
                WHERE run_id=? AND status='RUNNING'
                """,
                (now.isoformat(), run_id),
            )
            connection.execute(
                """
                UPDATE screening_run_universe
                SET item_status='RETRYABLE_FAILED',
                    last_error_type='LEASE_EXPIRED',
                    last_error_message='前一工作进程在完成标的前中断'
                WHERE run_id=? AND item_status='PROCESSING'
                """,
                (run_id,),
            )
            connection.execute(
                """
                UPDATE screening_runs SET status='RUNNING', finished_at=NULL
                WHERE run_id=?
                """,
                (run_id,),
            )
        return token

    def heartbeat_run_lease(
        self, run_id: str, worker_token: str, *, lease_seconds: int = 120
    ) -> None:
        now = datetime.now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE screening_run_leases
                SET heartbeat_at=?, lease_expires_at=?
                WHERE run_id=? AND worker_token=?
                """,
                (
                    now.isoformat(),
                    (now + timedelta(seconds=lease_seconds)).isoformat(),
                    run_id,
                    worker_token,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("运行租约已失效，停止写入以避免并发冲突")

    def release_run_lease(self, run_id: str, worker_token: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM screening_run_leases WHERE run_id=? AND worker_token=?",
                (run_id, worker_token),
            )

    def begin_item_attempt(self, run_id: str, symbol: str, trigger_type: str) -> str:
        if trigger_type not in {"INITIAL", "RESUME", "DATA_RETRY"}:
            raise ValueError(f"无效补跑触发类型: {trigger_type}")
        attempt_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            item = connection.execute(
                """
                SELECT attempt_count FROM screening_run_universe
                WHERE run_id=? AND symbol=?
                """,
                (run_id, symbol),
            ).fetchone()
            if item is None:
                raise ValueError(f"股票不属于固化运行股票池: {symbol}")
            attempt_no = int(item["attempt_count"]) + 1
            connection.execute(
                """
                UPDATE screening_run_universe
                SET item_status='PROCESSING', attempt_count=?, last_trigger=?,
                    last_attempt_started_at=?, last_error_type=NULL,
                    last_error_message=NULL
                WHERE run_id=? AND symbol=?
                """,
                (attempt_no, trigger_type, now, run_id, symbol),
            )
            connection.execute(
                """
                INSERT INTO tier1_item_attempts(
                    attempt_id, run_id, symbol, attempt_no, trigger_type,
                    status, started_at
                ) VALUES (?, ?, ?, ?, ?, 'RUNNING', ?)
                """,
                (attempt_id, run_id, symbol, attempt_no, trigger_type, now),
            )
        return attempt_id

    def finish_item_attempt(
        self,
        attempt_id: str,
        *,
        decision_status: str | None = None,
        data_status: str | None = None,
        error: BaseException | None = None,
    ) -> None:
        now = datetime.now().isoformat()
        with self.connect() as connection:
            attempt = connection.execute(
                "SELECT run_id, symbol FROM tier1_item_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if attempt is None:
                raise ValueError(f"未知逐股尝试: {attempt_id}")
            failed = error is not None
            error_type = type(error).__name__ if error is not None else None
            error_message = str(error) if error is not None else None
            connection.execute(
                """
                UPDATE tier1_item_attempts
                SET status=?, finished_at=?, error_type=?, error_message=?,
                    decision_status=?, data_status=? WHERE attempt_id=?
                """,
                (
                    "FAILED" if failed else "COMPLETED",
                    now,
                    error_type,
                    error_message,
                    decision_status,
                    data_status,
                    attempt_id,
                ),
            )
            connection.execute(
                """
                UPDATE screening_run_universe
                SET item_status=?, last_attempt_finished_at=?,
                    last_error_type=?, last_error_message=?
                WHERE run_id=? AND symbol=?
                """,
                (
                    "RETRYABLE_FAILED" if failed else "COMPLETED",
                    now,
                    error_type,
                    error_message,
                    attempt["run_id"],
                    attempt["symbol"],
                ),
            )

    def resume_targets(
        self,
        run_id: str,
        *,
        mode: str,
        symbols: Iterable[str] | None = None,
    ) -> list[UniverseItem]:
        if mode not in {"unfinished", "data_gaps"}:
            raise ValueError(f"未知补跑模式: {mode}")
        wanted = {str(item).zfill(6) for item in symbols or []}
        where = (
            "(u.item_status!='COMPLETED' OR d.symbol IS NULL)"
            if mode == "unfinished"
            else "(d.symbol IS NULL OR u.item_status='RETRYABLE_FAILED' "
            "OR d.screen_status IN ('DATA_ERROR','PENDING_DATA'))"
        )
        parameters: list[Any] = [run_id]
        symbol_clause = ""
        if wanted:
            placeholders = ",".join("?" for _ in wanted)
            symbol_clause = f" AND u.symbol IN ({placeholders})"
            parameters.extend(sorted(wanted))
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT u.symbol, u.stock_name, u.exchange
                FROM screening_run_universe u
                LEFT JOIN tier1_decisions d
                  ON d.run_id=u.run_id AND d.symbol=u.symbol
                WHERE u.run_id=? AND {where}{symbol_clause}
                ORDER BY u.position
                """,
                parameters,
            ).fetchall()
        return [
            UniverseItem(str(row["symbol"]), str(row["stock_name"]), str(row["exchange"]))
            for row in rows
        ]

    def mark_run_interrupted(self, run_id: str, error: BaseException) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE screening_runs SET status='INTERRUPTED', finished_at=?,
                    error_summary_json=? WHERE run_id=?
                """,
                (
                    datetime.now().isoformat(),
                    _json([f"{type(error).__name__}: {error}"]),
                    run_id,
                ),
            )

    def decision_price_dates(self, run_id: str) -> list[date]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT price_date FROM tier1_decisions
                WHERE run_id=? AND price_date IS NOT NULL ORDER BY price_date
                """,
                (run_id,),
            ).fetchall()
        return [date.fromisoformat(str(row["price_date"])) for row in rows]

    def decision_symbols(self, run_id: str) -> set[str]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT symbol FROM tier1_decisions WHERE run_id=?", (run_id,)
            ).fetchall()
        return {str(row["symbol"]) for row in rows}

    def has_retryable_items(self, run_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM screening_run_universe
                WHERE run_id=? AND item_status='RETRYABLE_FAILED' LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        return row is not None

    def save_quality_assessment(
        self,
        run_id: str,
        symbol: Optional[str],
        observation_id: int,
        assessment: QualityAssessment,
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO data_quality_assessments(
                    run_id, symbol, field_group, source_observation_id, provider,
                    capability, verification_status, severity, blocking,
                    issues_json, assessed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    symbol,
                    assessment.field_group,
                    observation_id,
                    assessment.provider,
                    assessment.capability.value,
                    assessment.verification_status.value,
                    assessment.severity.value,
                    int(assessment.blocking),
                    _json(assessment.to_dict()["issues"]),
                    datetime.now().isoformat(),
                ),
            )
        return int(cursor.lastrowid)

    def save_source_verification(
        self, report: dict[str, Any], *, run_id: Optional[str] = None
    ) -> str:
        self.migrate()
        verification_id = str(uuid.uuid4())
        with self.connect() as connection:
            if run_id is not None:
                run = connection.execute(
                    "SELECT as_of_date FROM screening_runs WHERE run_id=?", (run_id,)
                ).fetchone()
                if run is None:
                    raise ValueError(f"未知Tier1 run_id: {run_id}")
                if str(run["as_of_date"]) != str(report["as_of_date"]):
                    raise ValueError("多源验证as-of与绑定的Tier1运行不一致")
                decision = connection.execute(
                    """
                    SELECT 1 FROM tier1_decisions
                    WHERE run_id=? AND symbol=?
                    """,
                    (run_id, report["symbol"]),
                ).fetchone()
                if decision is None:
                    raise ValueError("多源验证股票不在绑定的Tier1运行中")
            connection.execute(
                """
                INSERT INTO source_verification_reports(
                    verification_id, run_id, symbol, as_of_date,
                    overall_verdict, providers_json, responses_json,
                    checks_json, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    verification_id,
                    run_id,
                    report["symbol"],
                    report["as_of_date"],
                    report["overall_verdict"],
                    _json(report.get("providers", [])),
                    _json(report.get("responses", [])),
                    _json(report.get("checks", [])),
                    report.get("note"),
                    datetime.now().isoformat(),
                ),
            )
        return verification_id

    def quality_summary(self, run_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            if not self._table_exists(connection, "data_quality_assessments"):
                return {
                    "assessment_count": 0,
                    "blocking_assessments": 0,
                    "quality_gate_passed": True,
                    "verification_counts": {},
                    "severity_counts": {},
                }
            rows = connection.execute(
                """
                SELECT verification_status, severity, blocking, COUNT(*) AS count
                FROM data_quality_assessments
                WHERE run_id=?
                GROUP BY verification_status, severity, blocking
                """,
                (run_id,),
            ).fetchall()
        verification_counts: dict[str, int] = {}
        severity_counts: dict[str, int] = {}
        blocking = 0
        total = 0
        for row in rows:
            count = int(row["count"])
            total += count
            blocking += count if int(row["blocking"]) else 0
            verification = str(row["verification_status"])
            severity = str(row["severity"])
            verification_counts[verification] = (
                verification_counts.get(verification, 0) + count
            )
            severity_counts[severity] = severity_counts.get(severity, 0) + count
        return {
            "assessment_count": total,
            "blocking_assessments": blocking,
            "quality_gate_passed": blocking == 0,
            "verification_counts": verification_counts,
            "severity_counts": severity_counts,
        }

    def save_observation(
        self,
        run_id: str,
        symbol: Optional[str],
        field_group: str,
        envelope: DataEnvelope,
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO source_observations(
                    run_id, symbol, field_group, provider, endpoint, request_json,
                    fetch_status, fetched_at, available_at, row_count, schema_hash,
                    payload_hash, error_type, error_message, quality_warnings_json,
                    raw_payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    symbol,
                    field_group,
                    envelope.provider,
                    envelope.endpoint,
                    _json(envelope.request),
                    envelope.status.value,
                    envelope.fetched_at.isoformat(),
                    _iso(envelope.available_at),
                    envelope.row_count,
                    envelope.schema_hash,
                    envelope.payload_hash,
                    envelope.error_type,
                    envelope.error_message,
                    _json(envelope.quality_warnings),
                    _json(envelope.raw_payload)
                    if envelope.raw_payload is not None
                    else None,
                ),
            )
            observation_id = int(cursor.lastrowid)
        envelope.observation_id = observation_id
        return observation_id

    def save_financial_facts(
        self, run_id: str, facts: Iterable[FinancialReportFact], observation_id: int
    ) -> None:
        rows = []
        for fact in facts:
            available_at = fact.announcement_date
            if fact.revision_at is not None:
                available_at = max(available_at, fact.revision_at.date())
            common = (
                run_id,
                fact.symbol,
                fact.report_period.isoformat(),
                "CUMULATIVE_REPORTED",
                fact.announcement_date.isoformat(),
                available_at.isoformat(),
                observation_id,
                _iso(fact.revision_at),
                _json(fact.raw),
            )
            rows.append(("operating_revenue", fact.operating_revenue, "CNY", *common))
            rows.append(("parent_net_profit", fact.parent_net_profit, "CNY", *common))
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO tier1_raw_metrics(
                    metric_name, raw_value, unit, run_id, symbol, report_period,
                    period_type, announcement_date, available_at,
                    source_observation_id, revision_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def save_quarterly_series(
        self, run_id: str, series: Iterable[QuarterlyMetric]
    ) -> None:
        rows = [
            (
                run_id,
                item.symbol,
                item.quarter.isoformat(),
                item.revenue_single,
                item.parent_np_single,
                item.prior_year_revenue_single,
                item.prior_year_parent_np_single,
                item.revenue_yoy,
                item.parent_np_yoy,
                int(item.revenue_comparable),
                int(item.parent_np_comparable),
                item.formula,
                _json(item.missing_fields),
                _json(item.source_observation_ids),
            )
            for item in series
        ]
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO tier1_quarterly_series(
                    run_id, symbol, quarter, revenue_single, parent_np_single,
                    prior_year_revenue_single, prior_year_parent_np_single,
                    revenue_yoy, parent_np_yoy, revenue_comparable,
                    parent_np_comparable, formula, missing_fields_json,
                    source_observation_ids_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, symbol, quarter) DO UPDATE SET
                    revenue_single=excluded.revenue_single,
                    parent_np_single=excluded.parent_np_single,
                    prior_year_revenue_single=excluded.prior_year_revenue_single,
                    prior_year_parent_np_single=excluded.prior_year_parent_np_single,
                    revenue_yoy=excluded.revenue_yoy,
                    parent_np_yoy=excluded.parent_np_yoy,
                    revenue_comparable=excluded.revenue_comparable,
                    parent_np_comparable=excluded.parent_np_comparable,
                    formula=excluded.formula,
                    missing_fields_json=excluded.missing_fields_json,
                    source_observation_ids_json=excluded.source_observation_ids_json
                """,
                rows,
            )

    def save_dividends(
        self,
        run_id: str,
        bundle: DividendBundle,
        calculation: DividendCalculation,
        observation_id: int,
    ) -> None:
        adjusted_lookup = {
            (item.ex_date, item.raw_per_share): item for item in calculation.events
        }
        rows = []
        for event in bundle.events:
            adjusted = adjusted_lookup.get(
                (event.ex_date, event.raw_cash_per_share_pre_tax)
            )
            rows.append(
                (
                    run_id,
                    event.symbol,
                    event.ex_date.isoformat(),
                    _iso(event.report_period),
                    _iso(event.announcement_date),
                    event.raw_cash_per_share_pre_tax,
                    adjusted.adjusted_per_share if adjusted else None,
                    adjusted.adjustment_factor if adjusted else None,
                    int(event.provider_adjusted),
                    event.status,
                    event.source,
                    observation_id,
                    _json(event.raw),
                )
            )
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO dividend_events(
                    run_id, symbol, ex_date, report_period, announcement_date,
                    raw_cash_per_share_pre_tax, adjusted_cash_per_share_pre_tax,
                    adjustment_factor, provider_adjusted, status, source,
                    source_observation_id, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def save_risk_status(
        self, run_id: str, status: RiskWarningStatus, observation_id: int
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO risk_warning_intervals(
                    run_id, symbol, as_of_date, is_risk_warning, security_name,
                    effective_date, source, source_observation_id, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, symbol) DO UPDATE SET
                    as_of_date=excluded.as_of_date,
                    is_risk_warning=excluded.is_risk_warning,
                    security_name=excluded.security_name,
                    effective_date=excluded.effective_date,
                    source=excluded.source,
                    source_observation_id=excluded.source_observation_id,
                    reason=excluded.reason
                """,
                (
                    run_id,
                    status.symbol,
                    status.as_of_date.isoformat(),
                    None
                    if status.is_risk_warning is None
                    else int(status.is_risk_warning),
                    status.security_name,
                    _iso(status.effective_date),
                    status.source,
                    observation_id,
                    status.reason,
                ),
            )

    def save_decision(
        self,
        run_id: str,
        decision: Tier1Decision,
        *,
        attempt_id: str | None = None,
    ) -> str:
        """Append an immutable decision version and refresh the current snapshot."""
        decision_id = str(uuid.uuid4())
        decision_json = _json(asdict(decision))
        decision_hash = hashlib.sha256(decision_json.encode("utf-8")).hexdigest()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if attempt_id is not None:
                attempt = connection.execute(
                    """
                    SELECT 1 FROM tier1_item_attempts
                    WHERE attempt_id=? AND run_id=? AND symbol=?
                    """,
                    (attempt_id, run_id, decision.symbol),
                ).fetchone()
                if attempt is None:
                    raise ValueError("决策与逐股尝试不属于同一运行及标的")
            decision_version = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(decision_version), 0) + 1
                    FROM tier1_decision_history WHERE run_id=? AND symbol=?
                    """,
                    (run_id, decision.symbol),
                ).fetchone()[0]
            )
            connection.execute(
                """
                INSERT INTO tier1_decision_history(
                    decision_id, run_id, symbol, attempt_id, decision_version,
                    calculation_version, decision_hash, decision_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    run_id,
                    decision.symbol,
                    attempt_id,
                    decision_version,
                    decision.calculation_version,
                    decision_hash,
                    decision_json,
                    decision.created_at.isoformat(),
                ),
            )
            connection.execute(
                """
                INSERT INTO tier1_decisions(
                    run_id, symbol, stock_name, as_of_date, price_date,
                    business_status, data_status, screen_status, selected_pe_ttm,
                    supplier_pe_ttm, self_pe_ttm, pe_selection_method,
                    dividend_yield_ttm, dividend_ttm_raw_per_share,
                    dividend_ttm_adjusted_per_share, risk_warning,
                    trend_quarters_json, revenue_yoy_sequence_json,
                    parent_np_yoy_sequence_json, failed_conditions_json,
                    pending_fields_json, error_fields_json, skipped_fields_json,
                    not_comparable_reasons_json, quality_warnings_json,
                    secondary_queues_json, calculation_version, created_at,
                    decision_id, decision_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, symbol) DO UPDATE SET
                    stock_name=excluded.stock_name,
                    as_of_date=excluded.as_of_date,
                    price_date=excluded.price_date,
                    business_status=excluded.business_status,
                    data_status=excluded.data_status,
                    screen_status=excluded.screen_status,
                    selected_pe_ttm=excluded.selected_pe_ttm,
                    supplier_pe_ttm=excluded.supplier_pe_ttm,
                    self_pe_ttm=excluded.self_pe_ttm,
                    pe_selection_method=excluded.pe_selection_method,
                    dividend_yield_ttm=excluded.dividend_yield_ttm,
                    dividend_ttm_raw_per_share=excluded.dividend_ttm_raw_per_share,
                    dividend_ttm_adjusted_per_share=excluded.dividend_ttm_adjusted_per_share,
                    risk_warning=excluded.risk_warning,
                    trend_quarters_json=excluded.trend_quarters_json,
                    revenue_yoy_sequence_json=excluded.revenue_yoy_sequence_json,
                    parent_np_yoy_sequence_json=excluded.parent_np_yoy_sequence_json,
                    failed_conditions_json=excluded.failed_conditions_json,
                    pending_fields_json=excluded.pending_fields_json,
                    error_fields_json=excluded.error_fields_json,
                    skipped_fields_json=excluded.skipped_fields_json,
                    not_comparable_reasons_json=excluded.not_comparable_reasons_json,
                    quality_warnings_json=excluded.quality_warnings_json,
                    secondary_queues_json=excluded.secondary_queues_json,
                    calculation_version=excluded.calculation_version,
                    created_at=excluded.created_at,
                    decision_id=excluded.decision_id,
                    decision_version=excluded.decision_version
                """,
                (
                    run_id,
                    decision.symbol,
                    decision.stock_name,
                    decision.as_of_date.isoformat(),
                    _iso(decision.price_date),
                    decision.business_status.value,
                    decision.data_status.value,
                    decision.screen_status,
                    decision.selected_pe_ttm,
                    decision.supplier_pe_ttm,
                    decision.self_pe_ttm,
                    decision.pe_selection_method,
                    decision.dividend_yield_ttm,
                    decision.dividend_ttm_raw_per_share,
                    decision.dividend_ttm_adjusted_per_share,
                    None
                    if decision.risk_warning is None
                    else int(decision.risk_warning),
                    _json(decision.trend_quarters),
                    _json(decision.revenue_yoy_sequence),
                    _json(decision.parent_np_yoy_sequence),
                    _json(decision.failed_conditions),
                    _json(decision.pending_fields),
                    _json(decision.error_fields),
                    _json(decision.skipped_fields),
                    _json(decision.not_comparable_reasons),
                    _json(decision.quality_warnings),
                    _json(decision.secondary_queues),
                    decision.calculation_version,
                    decision.created_at.isoformat(),
                    decision_id,
                    decision_version,
                ),
            )
            if attempt_id is not None:
                connection.execute(
                    "UPDATE tier1_item_attempts SET decision_id=? WHERE attempt_id=?",
                    (decision_id, attempt_id),
                )
        return decision_id

    def save_lineage(
        self,
        run_id: str,
        symbol: str,
        field_name: str,
        *,
        source_observation_id: Optional[int],
        source_period: Optional[str] = None,
        announcement_date: Optional[date] = None,
        available_at: Optional[date] = None,
        raw_value: Any = None,
        calculated_value: Any = None,
        calculation_note: Optional[str] = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO source_lineage(
                    run_id, symbol, field_name, source_observation_id,
                    source_period, announcement_date, available_at, fetched_at,
                    raw_value, calculated_value, calculation_note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    symbol,
                    field_name,
                    source_observation_id,
                    source_period,
                    _iso(announcement_date),
                    _iso(available_at),
                    datetime.now().isoformat(),
                    _json(raw_value) if raw_value is not None else None,
                    _json(calculated_value) if calculated_value is not None else None,
                    calculation_note,
                ),
            )

    def summary(self, run_id: str) -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT screen_status, COUNT(*) AS count
                FROM tier1_decisions WHERE run_id=? GROUP BY screen_status
                """,
                (run_id,),
            ).fetchall()
        return {str(row["screen_status"]): int(row["count"]) for row in rows}

    def decisions(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            if not self._table_exists(connection, "tier1_decisions"):
                return []
            rows = connection.execute(
                "SELECT * FROM tier1_decisions WHERE run_id=? ORDER BY symbol",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def run_record(self, run_id: str) -> Optional[dict[str, Any]]:
        with self.connect() as connection:
            if not self._table_exists(connection, "screening_runs"):
                return None
            row = connection.execute(
                "SELECT * FROM screening_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        return dict(row) if row is not None else None
