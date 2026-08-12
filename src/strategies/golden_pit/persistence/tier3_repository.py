"""Persistence and Stage B admission checks for the Stage C risk filter."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.strategies.golden_pit.persistence.tier1_repository import Tier1Repository


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class Tier3Repository:
    def __init__(self, db_path: str | Path):
        self.tier1 = Tier1Repository(db_path)
        self.db_path = Path(db_path)

    def connect(self):
        return self.tier1.connect()

    def migrate(self) -> None:
        self.tier1.migrate_all()

    def rollback_stage_c(self) -> None:
        down_path = (
            self.tier1.project_root
            / "scripts"
            / "migrations"
            / "004_tier3_risk_filter_down.sql"
        )
        with self.connect() as connection:
            self.tier1._execute_scripts_atomically(
                connection,
                [
                    down_path.read_text(encoding="utf-8"),
                    (
                        "DELETE FROM schema_migrations "
                        "WHERE version='004_tier3_risk_filter';"
                    ),
                ],
            )

    def tier2_pass_candidates(
        self, run_id: str, symbols: Iterable[str] | None = None
    ) -> list[dict[str, Any]]:
        self.migrate()
        requested = sorted(set(symbols or []))
        params: list[Any] = [run_id, run_id, run_id]
        symbol_filter = ""
        if requested:
            symbol_filter = f" AND p.symbol IN ({','.join('?' for _ in requested)})"
            params.extend(requested)
        with self.connect() as connection:
            run = connection.execute(
                "SELECT status FROM screening_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if run is None:
                raise ValueError(f"未知run_id: {run_id}")
            if str(run["status"]) not in {"FINISHED", "FINISHED_WITH_ERRORS"}:
                raise ValueError("上游运行尚未完成，不能进入Stage C")
            rows = connection.execute(
                f"""
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
                SELECT p.symbol, p.stock_name, p.as_of_date, p.package_id,
                       a.assessment_id, a.assessment_json,
                       h.review_id AS tier2_review_id, h.decision,
                       h.reviewer AS tier2_reviewer, h.rationale AS tier2_rationale
                FROM latest_package p
                JOIN latest_ai a ON a.package_id=p.package_id
                JOIN latest_review h ON h.assessment_id=a.assessment_id
                WHERE h.decision='PASS' {symbol_filter}
                ORDER BY p.symbol
                """,
                params,
            ).fetchall()
        result = [dict(row) for row in rows]
        if requested:
            admitted = {str(row["symbol"]) for row in result}
            missing = sorted(set(requested) - admitted)
            if missing:
                raise ValueError(
                    "以下股票没有最新Stage B人工PASS: " + ", ".join(missing)
                )
        return result

    def latest_tier2_pass(self, run_id: str, symbol: str) -> dict[str, Any] | None:
        rows = self.tier2_pass_candidates(run_id, [symbol])
        return rows[0] if rows else None

    def save_batch(self, records: list[dict[str, Any]]) -> list[str]:
        self.migrate()
        assessment_ids = []
        with self.connect() as connection:
            for record in records:
                current_tier2 = connection.execute(
                    """
                    WITH latest_package AS (
                        SELECT p.* FROM tier2_evidence_packages p
                        WHERE p.run_id=? AND p.symbol=?
                        ORDER BY p.created_at DESC, p.rowid DESC LIMIT 1
                    ), latest_ai AS (
                        SELECT a.* FROM ai_assessments a
                        WHERE a.run_id=? AND a.symbol=?
                        ORDER BY a.imported_at DESC, a.rowid DESC LIMIT 1
                    ), latest_review AS (
                        SELECT h.* FROM human_reviews h
                        WHERE h.run_id=? AND h.symbol=?
                        ORDER BY h.reviewed_at DESC, h.rowid DESC LIMIT 1
                    )
                    SELECT h.review_id, h.decision
                    FROM latest_package p
                    JOIN latest_ai a ON a.package_id=p.package_id
                    JOIN latest_review h ON h.assessment_id=a.assessment_id
                    """,
                    (
                        record["run_id"],
                        record["symbol"],
                        record["run_id"],
                        record["symbol"],
                        record["run_id"],
                        record["symbol"],
                    ),
                ).fetchone()
                if (
                    current_tier2 is None
                    or current_tier2["decision"] != "PASS"
                    or current_tier2["review_id"] != record["tier2_review_id"]
                ):
                    raise ValueError("保存前Stage B人工PASS已变化，整批拒绝写入")
                existing = connection.execute(
                    """
                    SELECT a.risk_assessment_id
                    FROM tier3_risk_inputs i
                    JOIN tier3_risk_assessments a ON a.input_id=i.input_id
                    WHERE i.tier2_review_id=? AND i.content_hash=?
                    """,
                    (record["tier2_review_id"], record["content_hash"]),
                ).fetchone()
                if existing is not None:
                    assessment_ids.append(str(existing["risk_assessment_id"]))
                    continue
                input_id = str(uuid.uuid4())
                assessment_id = str(uuid.uuid4())
                now = datetime.now(timezone.utc).isoformat()
                risk_input = record["risk_input"]
                assessment = record["assessment"]
                connection.execute(
                    """
                    INSERT INTO tier3_risk_inputs(
                        input_id, run_id, symbol, as_of_date, tier2_review_id,
                        schema_version, industry_model,
                        industry_classification_json, content_hash, input_json,
                        imported_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        input_id,
                        record["run_id"],
                        record["symbol"],
                        record["as_of_date"],
                        record["tier2_review_id"],
                        risk_input["schema_version"],
                        assessment["industry_model"],
                        _json(risk_input["industry_classification"]),
                        record["content_hash"],
                        _json(risk_input),
                        now,
                    ),
                )
                for check in assessment["normalized_checks"]:
                    connection.execute(
                        """
                        INSERT INTO tier3_risk_checks(
                            check_result_id, input_id, check_id, category,
                            rule_effect, status, confidence, facts_json,
                            inferences_json, counter_evidence_json, sources_json,
                            metrics_json, reasoning_summary
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid.uuid4()),
                            input_id,
                            check["check_id"],
                            check["category"],
                            check["rule_effect"],
                            check["status"],
                            check["confidence"],
                            _json(check["facts"]),
                            _json(check["inferences"]),
                            _json(check["counter_evidence"]),
                            _json(check["sources"]),
                            _json(check["metrics"]),
                            check["reasoning_summary"],
                        ),
                    )
                connection.execute(
                    """
                    INSERT INTO tier3_risk_assessments(
                        risk_assessment_id, input_id, run_id, symbol, as_of_date,
                        tier2_review_id, industry_model, industry_model_class,
                        rules_version, assessment_version, system_status,
                        data_status, hard_vetoes_json, risk_warnings_json,
                        value_trap_signals_json, supporting_evidence_json,
                        counter_evidence_json, unknown_checks_json,
                        falsification_conditions_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        assessment_id,
                        input_id,
                        record["run_id"],
                        record["symbol"],
                        record["as_of_date"],
                        record["tier2_review_id"],
                        assessment["industry_model"],
                        assessment["industry_model_class"],
                        assessment["rules_version"],
                        assessment["assessment_version"],
                        assessment["system_status"],
                        assessment["data_status"],
                        _json(assessment["hard_vetoes"]),
                        _json(assessment["risk_warnings"]),
                        _json(assessment["value_trap_signals"]),
                        _json(assessment["supporting_evidence"]),
                        _json(assessment["counter_evidence"]),
                        _json(assessment["unknown_checks"]),
                        _json(assessment["falsification_conditions"]),
                        now,
                    ),
                )
                assessment_ids.append(assessment_id)
        return assessment_ids

    def latest_assessment(self, run_id: str, symbol: str) -> dict[str, Any] | None:
        self.migrate()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM tier3_risk_assessments
                WHERE run_id=? AND symbol=?
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (run_id, symbol),
            ).fetchone()
        return dict(row) if row else None

    def save_human_review(
        self,
        *,
        risk_assessment_id: str,
        decision: str,
        reviewer: str,
        rationale: str,
        expected_run_id: str | None = None,
        expected_symbol: str | None = None,
    ) -> str:
        self.migrate()
        with self.connect() as connection:
            assessment = connection.execute(
                "SELECT * FROM tier3_risk_assessments WHERE risk_assessment_id=?",
                (risk_assessment_id,),
            ).fetchone()
            if assessment is None:
                raise ValueError(f"未知risk_assessment_id: {risk_assessment_id}")
            if expected_run_id and assessment["run_id"] != expected_run_id:
                raise ValueError("风险评估不属于指定run_id")
            if expected_symbol and assessment["symbol"] != expected_symbol:
                raise ValueError("风险评估不属于指定股票")
            latest = connection.execute(
                """
                SELECT risk_assessment_id FROM tier3_risk_assessments
                WHERE run_id=? AND symbol=?
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (assessment["run_id"], assessment["symbol"]),
            ).fetchone()
            if str(latest["risk_assessment_id"]) != risk_assessment_id:
                raise ValueError("只能复核该股票最新风险评估")
            current_tier2 = connection.execute(
                """
                WITH latest_package AS (
                    SELECT p.* FROM tier2_evidence_packages p
                    WHERE p.run_id=? AND p.symbol=?
                    ORDER BY p.created_at DESC, p.rowid DESC LIMIT 1
                ), latest_ai AS (
                    SELECT a.* FROM ai_assessments a
                    WHERE a.run_id=? AND a.symbol=?
                    ORDER BY a.imported_at DESC, a.rowid DESC LIMIT 1
                ), latest_review AS (
                    SELECT h.* FROM human_reviews h
                    WHERE h.run_id=? AND h.symbol=?
                    ORDER BY h.reviewed_at DESC, h.rowid DESC LIMIT 1
                )
                SELECT h.review_id, h.decision
                FROM latest_package p
                JOIN latest_ai a ON a.package_id=p.package_id
                JOIN latest_review h ON h.assessment_id=a.assessment_id
                """,
                (
                    assessment["run_id"],
                    assessment["symbol"],
                    assessment["run_id"],
                    assessment["symbol"],
                    assessment["run_id"],
                    assessment["symbol"],
                ),
            ).fetchone()
            if (
                current_tier2 is None
                or current_tier2["decision"] != "PASS"
                or current_tier2["review_id"] != assessment["tier2_review_id"]
            ):
                raise ValueError("风险评估绑定的Stage B人工PASS已不是最新版本")
            rank = {"REJECT": 0, "REVIEW": 1, "PASS": 2}
            if rank[decision] > rank[str(assessment["system_status"])]:
                raise ValueError("人工决定不能覆盖硬否决、警告或数据缺口而上调")
            if not reviewer.strip() or len(rationale.strip()) < 5:
                raise ValueError("复核人不得为空且复核理由至少5个字符")
            previous = connection.execute(
                """
                SELECT review_id FROM tier3_human_reviews
                WHERE run_id=? AND symbol=?
                ORDER BY reviewed_at DESC, rowid DESC LIMIT 1
                """,
                (assessment["run_id"], assessment["symbol"]),
            ).fetchone()
            review_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO tier3_human_reviews(
                    review_id, risk_assessment_id, run_id, symbol, decision,
                    reviewer, rationale, reviewed_at, supersedes_review_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    risk_assessment_id,
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

    def summary(self, run_id: str) -> list[dict[str, Any]]:
        self.migrate()
        with self.connect() as connection:
            rows = connection.execute(
                """
                WITH latest_assessment AS (
                    SELECT a.* FROM tier3_risk_assessments a
                    WHERE a.run_id=? AND a.rowid=(
                        SELECT a2.rowid FROM tier3_risk_assessments a2
                        WHERE a2.run_id=a.run_id AND a2.symbol=a.symbol
                        ORDER BY a2.created_at DESC, a2.rowid DESC LIMIT 1
                    )
                ), latest_review AS (
                    SELECT h.* FROM tier3_human_reviews h
                    WHERE h.run_id=? AND h.rowid=(
                        SELECT h2.rowid FROM tier3_human_reviews h2
                        WHERE h2.run_id=h.run_id AND h2.symbol=h.symbol
                        ORDER BY h2.reviewed_at DESC, h2.rowid DESC LIMIT 1
                    )
                ), latest_package AS (
                    SELECT p.* FROM tier2_evidence_packages p
                    WHERE p.run_id=? AND p.rowid=(
                        SELECT p2.rowid FROM tier2_evidence_packages p2
                        WHERE p2.run_id=p.run_id AND p2.symbol=p.symbol
                        ORDER BY p2.created_at DESC, p2.rowid DESC LIMIT 1
                    )
                ), latest_ai AS (
                    SELECT ai.* FROM ai_assessments ai
                    WHERE ai.run_id=? AND ai.rowid=(
                        SELECT ai2.rowid FROM ai_assessments ai2
                        WHERE ai2.run_id=ai.run_id AND ai2.symbol=ai.symbol
                        ORDER BY ai2.imported_at DESC, ai2.rowid DESC LIMIT 1
                    )
                ), latest_tier2_review AS (
                    SELECT r.* FROM human_reviews r
                    WHERE r.run_id=? AND r.rowid=(
                        SELECT r2.rowid FROM human_reviews r2
                        WHERE r2.run_id=r.run_id AND r2.symbol=r.symbol
                        ORDER BY r2.reviewed_at DESC, r2.rowid DESC LIMIT 1
                    )
                )
                SELECT a.*, h.decision AS human_decision, h.reviewer,
                       h.rationale AS human_rationale, h.reviewed_at,
                       CASE WHEN tr.review_id=a.tier2_review_id
                                  AND tr.decision='PASS'
                             THEN 1 ELSE 0 END AS upstream_current
                FROM latest_assessment a
                LEFT JOIN latest_review h
                  ON h.risk_assessment_id=a.risk_assessment_id
                LEFT JOIN latest_package p ON p.symbol=a.symbol
                LEFT JOIN latest_ai ai ON ai.package_id=p.package_id
                LEFT JOIN latest_tier2_review tr ON tr.assessment_id=ai.assessment_id
                ORDER BY a.symbol
                """,
                (run_id, run_id, run_id, run_id, run_id),
            ).fetchall()
        return [dict(row) for row in rows]
