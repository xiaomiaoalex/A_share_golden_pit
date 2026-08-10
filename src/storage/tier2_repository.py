"""Append-only persistence for the Stage B Tier2 human-AI workflow."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.storage.tier1_repository import Tier1Repository


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class Tier2Repository:
    """Stores immutable packages/assessments and append-only human reviews."""

    def __init__(self, db_path: str | Path):
        self.tier1 = Tier1Repository(db_path)
        self.db_path = Path(db_path)

    def connect(self) -> sqlite3.Connection:
        return self.tier1.connect()

    def migrate(self) -> None:
        self.tier1.migrate_through_stage_b()

    def rollback_stage_b(self) -> None:
        tier3_down_path = (
            self.tier1.project_root
            / "scripts"
            / "migrations"
            / "004_tier3_risk_filter_down.sql"
        )
        down_path = (
            self.tier1.project_root
            / "scripts"
            / "migrations"
            / "003_tier2_human_ai_down.sql"
        )
        with self.connect() as connection:
            connection.executescript(tier3_down_path.read_text(encoding="utf-8"))
            connection.executescript(down_path.read_text(encoding="utf-8"))
            if self.tier1._table_exists(connection, "schema_migrations"):
                connection.execute(
                    "DELETE FROM schema_migrations WHERE version=?",
                    ("003_tier2_human_ai",),
                )
                connection.execute(
                    "DELETE FROM schema_migrations WHERE version=?",
                    ("004_tier3_risk_filter",),
                )

    def tier1_pass_candidates(
        self, run_id: str, symbols: Iterable[str] | None = None
    ) -> list[dict[str, Any]]:
        self.migrate()
        params: list[Any] = [run_id]
        sql = """
            SELECT * FROM tier1_decisions
            WHERE run_id=? AND screen_status='PASS'
        """
        normalized = sorted(set(symbols or []))
        if normalized:
            sql += f" AND symbol IN ({','.join('?' for _ in normalized)})"
            params.extend(normalized)
        sql += " ORDER BY symbol"
        with self.connect() as connection:
            run = connection.execute(
                "SELECT * FROM screening_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if run is None:
                raise ValueError(f"未知Tier1 run_id: {run_id}")
            if str(run["status"]) not in {"FINISHED", "FINISHED_WITH_ERRORS"}:
                raise ValueError("Tier1运行尚未完成，不能生成Tier2证据包")
            rows = connection.execute(sql, params).fetchall()
        result = [dict(row) for row in rows]
        if normalized:
            exported = {str(row["symbol"]) for row in result}
            missing = sorted(set(normalized) - exported)
            if missing:
                raise ValueError(
                    "以下股票不在该运行的Tier1 PASS集合中: " + ", ".join(missing)
                )
        return result

    def evidence_rows(self, run_id: str, symbol: str) -> dict[str, Any]:
        """Read only point-in-time records tied to the same Tier1 run."""

        with self.connect() as connection:
            quarterly = connection.execute(
                """
                SELECT * FROM tier1_quarterly_series
                WHERE run_id=? AND symbol=? ORDER BY quarter
                """,
                (run_id, symbol),
            ).fetchall()
            raw_metrics = connection.execute(
                """
                SELECT metric_name, report_period, period_type, raw_value, unit,
                       announcement_date, available_at, revision_at,
                       source_observation_id
                FROM tier1_raw_metrics
                WHERE run_id=? AND symbol=? ORDER BY report_period, metric_name
                """,
                (run_id, symbol),
            ).fetchall()
            dividends = connection.execute(
                """
                SELECT ex_date, report_period, announcement_date,
                       raw_cash_per_share_pre_tax,
                       adjusted_cash_per_share_pre_tax, adjustment_factor,
                       provider_adjusted, status, source, source_observation_id
                FROM dividend_events
                WHERE run_id=? AND symbol=? ORDER BY ex_date
                """,
                (run_id, symbol),
            ).fetchall()
            lineage = connection.execute(
                """
                SELECT field_name, source_observation_id, source_period,
                       announcement_date, available_at, fetched_at, raw_value,
                       calculated_value, calculation_note
                FROM source_lineage
                WHERE run_id=? AND symbol=? ORDER BY id
                """,
                (run_id, symbol),
            ).fetchall()
            observations = connection.execute(
                """
                SELECT id, field_group, provider, endpoint, fetch_status,
                       fetched_at, available_at, row_count, schema_hash,
                       payload_hash, quality_warnings_json
                FROM source_observations
                WHERE run_id=? AND (symbol=? OR symbol IS NULL) ORDER BY id
                """,
                (run_id, symbol),
            ).fetchall()
            quality = connection.execute(
                """
                SELECT field_group, source_observation_id, provider, capability,
                       verification_status, severity, blocking, issues_json,
                       assessed_at
                FROM data_quality_assessments
                WHERE run_id=? AND (symbol=? OR symbol IS NULL) ORDER BY id
                """,
                (run_id, symbol),
            ).fetchall()
            verification = connection.execute(
                """
                SELECT verification_id, overall_verdict, providers_json,
                       checks_json, note, created_at
                FROM source_verification_reports
                WHERE run_id=? AND symbol=? ORDER BY created_at
                """,
                (run_id, symbol),
            ).fetchall()
        return {
            "quarterly_series": [dict(row) for row in quarterly],
            "raw_financial_metrics": [dict(row) for row in raw_metrics],
            "dividend_events": [dict(row) for row in dividends],
            "source_lineage": [dict(row) for row in lineage],
            "source_observations": [dict(row) for row in observations],
            "data_quality_assessments": [dict(row) for row in quality],
            "source_verification_reports": [dict(row) for row in verification],
        }

    def save_evidence_package(
        self,
        package: dict[str, Any],
        *,
        json_path: str | None = None,
        markdown_path: str | None = None,
    ) -> str:
        self.migrate()
        package_id = package["package_id"]
        with self.connect() as connection:
            existing = connection.execute(
                """
                SELECT package_id FROM tier2_evidence_packages
                WHERE run_id=? AND symbol=? AND content_hash=?
                """,
                (package["run_id"], package["symbol"], package["content_hash"]),
            ).fetchone()
            if existing is not None:
                package_id = str(existing["package_id"])
                connection.execute(
                    """
                    UPDATE tier2_evidence_packages
                    SET json_path=COALESCE(?, json_path),
                        markdown_path=COALESCE(?, markdown_path)
                    WHERE package_id=?
                    """,
                    (json_path, markdown_path, package_id),
                )
                return package_id
            connection.execute(
                """
                INSERT INTO tier2_evidence_packages(
                    package_id, run_id, symbol, stock_name, as_of_date,
                    package_version, content_hash, coverage_status,
                    missing_sections_json, evidence_json, json_path,
                    markdown_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    package_id,
                    package["run_id"],
                    package["symbol"],
                    package["stock_name"],
                    package["as_of_date"],
                    package["package_version"],
                    package["content_hash"],
                    package["coverage_status"],
                    _json(package["missing_sections"]),
                    _json(package["evidence"]),
                    json_path,
                    markdown_path,
                    package["created_at"],
                ),
            )
        return package_id

    def package(self, package_id: str) -> dict[str, Any] | None:
        self.migrate()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM tier2_evidence_packages WHERE package_id=?",
                (package_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def latest_package(self, run_id: str, symbol: str) -> dict[str, Any] | None:
        self.migrate()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM tier2_evidence_packages
                WHERE run_id=? AND symbol=?
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (run_id, symbol),
            ).fetchone()
        return dict(row) if row is not None else None

    def save_assessments_atomic(self, records: list[dict[str, Any]]) -> list[str]:
        """Persist only after all records have already passed validation."""

        self.migrate()
        ids: list[str] = []
        with self.connect() as connection:
            for record in records:
                existing = connection.execute(
                    """
                    SELECT assessment_id FROM ai_assessments
                    WHERE package_id=? AND content_hash=?
                    """,
                    (record["package_id"], record["content_hash"]),
                ).fetchone()
                if existing is not None:
                    ids.append(str(existing["assessment_id"]))
                    continue
                assessment_id = str(uuid.uuid4())
                connection.execute(
                    """
                    INSERT INTO ai_assessments(
                        assessment_id, package_id, run_id, symbol, as_of_date,
                        schema_version, ai_provider, ai_model,
                        ai_recommendation, system_recommendation, content_hash,
                        assessment_json, imported_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        assessment_id,
                        record["package_id"],
                        record["run_id"],
                        record["symbol"],
                        record["as_of_date"],
                        record["schema_version"],
                        record["ai_provider"],
                        record.get("ai_model"),
                        record["ai_recommendation"],
                        record["system_recommendation"],
                        record["content_hash"],
                        _json(record["assessment"]),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                ids.append(assessment_id)
        return ids

    def latest_assessment(self, run_id: str, symbol: str) -> dict[str, Any] | None:
        self.migrate()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM ai_assessments
                WHERE run_id=? AND symbol=?
                ORDER BY imported_at DESC, rowid DESC LIMIT 1
                """,
                (run_id, symbol),
            ).fetchone()
        return dict(row) if row is not None else None

    def save_human_review(
        self,
        *,
        assessment_id: str,
        decision: str,
        reviewer: str,
        rationale: str,
        expected_run_id: str | None = None,
        expected_symbol: str | None = None,
    ) -> str:
        self.migrate()
        with self.connect() as connection:
            assessment = connection.execute(
                "SELECT * FROM ai_assessments WHERE assessment_id=?",
                (assessment_id,),
            ).fetchone()
            if assessment is None:
                raise ValueError(f"未知assessment_id: {assessment_id}")
            if expected_run_id is not None and assessment["run_id"] != expected_run_id:
                raise ValueError("AI评估不属于指定run_id")
            if expected_symbol is not None and assessment["symbol"] != expected_symbol:
                raise ValueError("AI评估不属于指定股票")
            latest_package = connection.execute(
                """
                SELECT package_id FROM tier2_evidence_packages
                WHERE run_id=? AND symbol=?
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (assessment["run_id"], assessment["symbol"]),
            ).fetchone()
            if (
                latest_package is None
                or str(latest_package["package_id"]) != str(assessment["package_id"])
            ):
                raise ValueError("AI评估绑定的证据包已不是最新版本")
            latest_assessment = connection.execute(
                """
                SELECT assessment_id FROM ai_assessments
                WHERE run_id=? AND symbol=?
                ORDER BY imported_at DESC, rowid DESC LIMIT 1
                """,
                (assessment["run_id"], assessment["symbol"]),
            ).fetchone()
            if str(latest_assessment["assessment_id"]) != assessment_id:
                raise ValueError("只能复核该股票最新的AI评估")
            rank = {"REJECT": 0, "REVIEW": 1, "PASS": 2}
            if rank[decision] > rank[str(assessment["system_recommendation"])]:
                raise ValueError("人工决定不能覆盖关键否决或证据不足而上调")
            if not reviewer.strip():
                raise ValueError("复核人不得为空")
            if len(rationale.strip()) < 5:
                raise ValueError("人工复核理由过短")
            previous = connection.execute(
                """
                SELECT review_id FROM human_reviews
                WHERE run_id=? AND symbol=? ORDER BY reviewed_at DESC, rowid DESC LIMIT 1
                """,
                (assessment["run_id"], assessment["symbol"]),
            ).fetchone()
            review_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO human_reviews(
                    review_id, assessment_id, run_id, symbol, decision,
                    reviewer, rationale, reviewed_at, supersedes_review_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    assessment_id,
                    assessment["run_id"],
                    assessment["symbol"],
                    decision,
                    reviewer.strip(),
                    rationale.strip(),
                    datetime.now(timezone.utc).isoformat(),
                    str(previous["review_id"]) if previous else None,
                ),
            )
        return review_id

    def review_summary(self, run_id: str) -> list[dict[str, Any]]:
        self.migrate()
        with self.connect() as connection:
            rows = connection.execute(
                """
                WITH latest_package AS (
                    SELECT p.* FROM tier2_evidence_packages p
                    WHERE p.run_id=? AND p.rowid=(
                        SELECT p2.rowid FROM tier2_evidence_packages p2
                        WHERE p2.run_id=p.run_id AND p2.symbol=p.symbol
                        ORDER BY p2.created_at DESC, p2.rowid DESC LIMIT 1
                    )
                ), latest_ai AS (
                    SELECT a.* FROM ai_assessments a
                    WHERE a.run_id=? AND a.rowid=(
                        SELECT a2.rowid FROM ai_assessments a2
                        WHERE a2.run_id=a.run_id AND a2.symbol=a.symbol
                        ORDER BY a2.imported_at DESC, a2.rowid DESC LIMIT 1
                    )
                ), latest_review AS (
                    SELECT h.* FROM human_reviews h
                    WHERE h.run_id=? AND h.rowid=(
                        SELECT h2.rowid FROM human_reviews h2
                        WHERE h2.run_id=h.run_id AND h2.symbol=h.symbol
                        ORDER BY h2.reviewed_at DESC, h2.rowid DESC LIMIT 1
                    )
                )
                SELECT p.symbol, p.stock_name, p.coverage_status,
                       p.missing_sections_json, p.package_id,
                       a.assessment_id, a.ai_recommendation,
                       a.system_recommendation, a.assessment_json,
                       h.decision AS human_decision, h.reviewer,
                       h.rationale, h.reviewed_at
                FROM latest_package p
                LEFT JOIN latest_ai a ON a.package_id=p.package_id
                LEFT JOIN latest_review h ON h.assessment_id=a.assessment_id
                ORDER BY p.symbol
                """,
                (run_id, run_id, run_id),
            ).fetchall()
        return [dict(row) for row in rows]
