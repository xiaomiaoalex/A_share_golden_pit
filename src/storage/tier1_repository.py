"""SQLite repository for Stage A Tier1 v2 data.

Stage A uses additive, versioned SQLite migrations and stores every run
independently.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from config.tier1 import Tier1Config
from src.data.point_in_time.contracts import DataEnvelope, DividendBundle
from src.data.quality.types import QualityAssessment
from src.screening.tier1_v2.contracts import (
    FinancialReportFact,
    QuarterlyMetric,
    RiskWarningStatus,
    Tier1Decision,
)
from src.screening.tier1_v2.metrics import DividendCalculation

MIGRATIONS = (
    ("001_tier1_v2", "001_tier1_v2_up.sql", "Stage A strict Tier1 v2"),
    (
        "002_tier1_data_quality",
        "002_tier1_data_quality_up.sql",
        "Tier1 business data quality assessments",
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
        self.project_root = Path(__file__).resolve().parents[2]

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def migrate(self) -> None:
        self._apply_migrations(MIGRATIONS)

    def migrate_through_stage_b(self) -> None:
        self._apply_migrations(MIGRATIONS + STAGE_B_MIGRATIONS)

    def migrate_all(self) -> None:
        self._apply_migrations(MIGRATIONS + STAGE_B_MIGRATIONS + STAGE_C_MIGRATIONS)

    def _apply_migrations(self, migrations) -> None:
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
        with self.connect() as connection:
            self._execute_scripts_atomically(
                connection,
                [
                    tier3_down.read_text(encoding="utf-8"),
                    tier2_down.read_text(encoding="utf-8"),
                    quality_down.read_text(encoding="utf-8"),
                    down_path.read_text(encoding="utf-8"),
                    "DELETE FROM schema_migrations WHERE version IN "
                    "('001_tier1_v2','002_tier1_data_quality',"
                    "'003_tier2_human_ai','004_tier3_risk_filter');",
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
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO screening_runs(
                    run_id, as_of_date, calculation_version, config_json,
                    status, started_at
                ) VALUES (?, ?, ?, ?, 'RUNNING', ?)
                """,
                (
                    run_id,
                    as_of_date.isoformat(),
                    config.calculation_version,
                    _json(config.to_dict()),
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
                INSERT OR REPLACE INTO tier1_raw_metrics(
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
                INSERT OR REPLACE INTO tier1_quarterly_series(
                    run_id, symbol, quarter, revenue_single, parent_np_single,
                    prior_year_revenue_single, prior_year_parent_np_single,
                    revenue_yoy, parent_np_yoy, revenue_comparable,
                    parent_np_comparable, formula, missing_fields_json,
                    source_observation_ids_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                INSERT OR REPLACE INTO risk_warning_intervals(
                    run_id, symbol, as_of_date, is_risk_warning, security_name,
                    effective_date, source, source_observation_id, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def save_decision(self, run_id: str, decision: Tier1Decision) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO tier1_decisions(
                    run_id, symbol, stock_name, as_of_date, price_date,
                    business_status, data_status, screen_status, selected_pe_ttm,
                    supplier_pe_ttm, self_pe_ttm, pe_selection_method,
                    dividend_yield_ttm, dividend_ttm_raw_per_share,
                    dividend_ttm_adjusted_per_share, risk_warning,
                    trend_quarters_json, revenue_yoy_sequence_json,
                    parent_np_yoy_sequence_json, failed_conditions_json,
                    pending_fields_json, error_fields_json, skipped_fields_json,
                    not_comparable_reasons_json, quality_warnings_json,
                    secondary_queues_json, calculation_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )

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
