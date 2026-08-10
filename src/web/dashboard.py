"""Read-model used by the local web console.

The web layer intentionally reads the formal SQLite schema instead of creating a
parallel application database.  All state-changing reviews are delegated to the
existing repositories so their downgrade-only invariants remain authoritative.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def _json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


class DashboardService:
    """Build frontend-friendly projections from the formal workflow tables."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _tables(connection: sqlite3.Connection) -> set[str]:
        return {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    def overview(self, run_id: str | None = None) -> dict[str, Any]:
        with self.connect() as connection:
            tables = self._tables(connection)
            if "screening_runs" not in tables:
                return self._empty_overview()

            runs = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT run_id, as_of_date, status, started_at, finished_at,
                           universe_size, calculation_version
                    FROM screening_runs
                    ORDER BY started_at DESC, rowid DESC LIMIT 30
                    """
                ).fetchall()
            ]
            self._add_run_progress(connection, runs, tables)
            selected_id = run_id or (runs[0]["run_id"] if runs else None)
            if selected_id is None:
                return self._empty_overview(runs)

            run_row = connection.execute(
                "SELECT * FROM screening_runs WHERE run_id=?", (selected_id,)
            ).fetchone()
            if run_row is None:
                raise ValueError(f"未找到运行记录: {selected_id}")
            run = dict(run_row)
            progress = next(
                (item.get("progress") for item in runs if item["run_id"] == selected_id),
                None,
            )
            run["progress"] = progress
            run["config"] = _json(run.pop("config_json", None), {})
            run["errors"] = _json(run.pop("error_summary_json", None), [])
            run["data_quality"] = _json(
                run.pop("data_quality_summary_json", None), {}
            )

            candidates = self._candidates(connection, selected_id, tables)
            quality = self._quality(connection, selected_id, tables)
            activity = self._activity(connection, selected_id, tables)
            counts = Counter(row["screen_status"] for row in candidates)
            stage_a_pass = sum(row["screen_status"] == "PASS" for row in candidates)
            stage_b_pass = sum(row["stage_b_status"] == "PASS" for row in candidates)
            stage_c_pass = sum(row["stage_c_status"] == "PASS" for row in candidates)
            pending_review = sum(
                row["stage_b_status"] == "待人工复核"
                or row["stage_c_status"] == "待人工复核"
                for row in candidates
            )
            next_action = self._next_action(run, candidates)
            return {
                "runs": runs,
                "run": run,
                "summary": {
                    "universe": (
                        run.get("universe_size")
                        or (run.get("progress") or {}).get("total")
                        or len(candidates)
                    ),
                    "stage_a_pass": stage_a_pass,
                    "stage_b_pass": stage_b_pass,
                    "stage_c_pass": stage_c_pass,
                    "pending_review": pending_review,
                    "screen_status_counts": dict(counts),
                },
                "pipeline": [
                    {
                        "key": "A",
                        "name": "客观初筛",
                        "caption": "估值 · 分红 · 趋势 · ST",
                        "total": len(candidates),
                        "passed": stage_a_pass,
                    },
                    {
                        "key": "B",
                        "name": "证据研究",
                        "caption": "证据包 · AI研究 · 人工确认",
                        "total": stage_a_pass,
                        "passed": stage_b_pass,
                    },
                    {
                        "key": "C",
                        "name": "风险终审",
                        "caption": "行业模型 · 价值陷阱 · 终审",
                        "total": stage_b_pass,
                        "passed": stage_c_pass,
                    },
                ],
                "candidates": candidates,
                "quality": quality,
                "activity": activity,
                "next_action": next_action,
            }

    def running_runs(self) -> list[dict[str, Any]]:
        """Return live Stage A runs with database-backed progress."""
        with self.connect() as connection:
            tables = self._tables(connection)
            if "screening_runs" not in tables:
                return []
            runs = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT run_id, as_of_date, status, started_at, finished_at,
                           universe_size, calculation_version
                    FROM screening_runs WHERE status='RUNNING'
                    ORDER BY started_at DESC, rowid DESC
                    """
                ).fetchall()
            ]
            self._add_run_progress(connection, runs, tables)
            return runs

    @staticmethod
    def _add_run_progress(
        connection: sqlite3.Connection,
        runs: list[dict[str, Any]],
        tables: set[str],
    ) -> None:
        if not runs:
            return
        processed: dict[str, dict[str, Any]] = {}
        if "tier1_decisions" in tables:
            for row in connection.execute(
                """
                SELECT run_id, COUNT(*) AS processed_count,
                       MIN(created_at) AS first_completed_at,
                       MAX(created_at) AS last_completed_at
                FROM tier1_decisions GROUP BY run_id
                """
            ).fetchall():
                processed[str(row["run_id"])] = dict(row)
        observed_totals: dict[str, int] = {}
        if "source_observations" in tables:
            for row in connection.execute(
                """
                SELECT run_id, MAX(row_count) AS observed_total
                FROM source_observations
                WHERE field_group='universe' AND fetch_status='SUCCESS'
                GROUP BY run_id
                """
            ).fetchall():
                if row["observed_total"] is not None:
                    observed_totals[str(row["run_id"])] = int(row["observed_total"])

        now = datetime.now()
        for run in runs:
            run_id = str(run["run_id"])
            stats = processed.get(run_id, {})
            count = int(stats.get("processed_count") or 0)
            total = run.get("universe_size")
            if total is None:
                total = observed_totals.get(run_id)
            total = int(total) if total is not None else None
            status = str(run.get("status"))
            percent = None
            if total and total > 0:
                percent = min(100.0, count / total * 100)
                if status == "RUNNING":
                    percent = min(percent, 99.9)

            started = DashboardService._parse_datetime(run.get("started_at"))
            elapsed = max(0, int((now - started).total_seconds())) if started else None
            seconds_per_item = None
            first = DashboardService._parse_datetime(stats.get("first_completed_at"))
            last = DashboardService._parse_datetime(stats.get("last_completed_at"))
            if count >= 3 and first and last and last > first:
                seconds_per_item = (last - first).total_seconds() / (count - 1)
            eta = None
            if (
                status == "RUNNING"
                and total is not None
                and count < total
                and seconds_per_item is not None
            ):
                eta = max(0, int((total - count) * seconds_per_item))
            source_health = (
                DashboardService._source_health(connection, run_id, now, started)
                if status == "RUNNING" and "source_observations" in tables
                else None
            )
            recovery = DashboardService._recovery_status(
                connection,
                run,
                tables,
                now,
                source_health,
                count,
                total,
            )
            run["progress"] = {
                "processed": count,
                "total": total,
                "percent": round(percent, 2) if percent is not None else None,
                "elapsed_seconds": elapsed,
                "eta_seconds": eta,
                "seconds_per_item": (
                    round(seconds_per_item, 2)
                    if seconds_per_item is not None
                    else None
                ),
                "updated_at": stats.get("last_completed_at"),
                "source_health": source_health,
                "recovery": recovery,
            }

    @staticmethod
    def _recovery_status(
        connection: sqlite3.Connection,
        run: dict[str, Any],
        tables: set[str],
        now: datetime,
        source_health: dict[str, Any] | None,
        processed_count: int,
        total: int | None,
    ) -> dict[str, Any]:
        run_id = str(run["run_id"])
        status = str(run.get("status"))
        has_snapshot = False
        snapshot_source = None
        unfinished_count = max(0, (total or processed_count) - processed_count)
        data_gap_count = 0
        active_lease = False
        if "screening_universe_snapshots" in tables:
            snapshot = connection.execute(
                """
                SELECT snapshot_source FROM screening_universe_snapshots
                WHERE run_id=?
                """,
                (run_id,),
            ).fetchone()
            has_snapshot = snapshot is not None
            snapshot_source = str(snapshot["snapshot_source"]) if snapshot else None
        if "screening_run_universe" in tables and has_snapshot:
            counts = connection.execute(
                """
                SELECT
                    SUM(CASE WHEN u.item_status!='COMPLETED' OR d.symbol IS NULL
                             THEN 1 ELSE 0 END) AS unfinished_count,
                    SUM(CASE WHEN d.symbol IS NULL
                                  OR u.item_status='RETRYABLE_FAILED'
                                  OR d.screen_status IN ('DATA_ERROR','PENDING_DATA')
                             THEN 1 ELSE 0 END) AS data_gap_count
                FROM screening_run_universe u
                LEFT JOIN tier1_decisions d
                  ON d.run_id=u.run_id AND d.symbol=u.symbol
                WHERE u.run_id=?
                """,
                (run_id,),
            ).fetchone()
            unfinished_count = int(counts["unfinished_count"] or 0)
            data_gap_count = int(counts["data_gap_count"] or 0)
        elif "tier1_decisions" in tables:
            data_gap_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM tier1_decisions
                    WHERE run_id=? AND screen_status IN ('DATA_ERROR','PENDING_DATA')
                    """,
                    (run_id,),
                ).fetchone()[0]
            )
        if "screening_run_leases" in tables:
            lease = connection.execute(
                "SELECT lease_expires_at FROM screening_run_leases WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if lease is not None:
                expiry = DashboardService._parse_datetime(lease["lease_expires_at"])
                active_lease = bool(expiry and expiry > now)
        idle_seconds = (
            source_health.get("idle_seconds") if source_health is not None else None
        )
        stale_running = (
            status == "RUNNING"
            and idle_seconds is not None
            and idle_seconds >= 180
        )
        can_resume = (
            unfinished_count > 0
            and not active_lease
            and (status == "INTERRUPTED" or stale_running)
        )
        can_retry_data = (
            data_gap_count > 0
            and not active_lease
            and status in {"FINISHED", "FINISHED_WITH_ERRORS", "INTERRUPTED"}
        )
        return {
            "has_snapshot": has_snapshot,
            "snapshot_source": snapshot_source,
            "unfinished_count": unfinished_count,
            "data_gap_count": data_gap_count,
            "active_lease": active_lease,
            "stale_running": stale_running,
            "can_resume": can_resume,
            "can_retry_data": can_retry_data,
        }

    @staticmethod
    def _source_health(
        connection: sqlite3.Connection,
        run_id: str,
        now: datetime,
        started_at: datetime | None,
    ) -> dict[str, Any]:
        rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT symbol, field_group, provider, fetch_status, fetched_at,
                       error_type, error_message, quality_warnings_json,
                       raw_payload_json
                FROM source_observations WHERE run_id=?
                ORDER BY id DESC LIMIT 80
                """,
                (run_id,),
            ).fetchall()
        ]
        latest_at = DashboardService._parse_datetime(
            rows[0].get("fetched_at") if rows else None
        ) or started_at
        idle_seconds = (
            max(0, int((now - latest_at).total_seconds())) if latest_at else None
        )
        errors = [
            row
            for row in rows
            if str(row.get("fetch_status")) in {"ERROR", "SCHEMA_ERROR"}
        ]
        fallback_count = 0
        for row in rows:
            warnings = _json(row.get("quality_warnings_json"), [])
            raw = _json(row.get("raw_payload_json"), {})
            trace = raw.get("fallback_trace", []) if isinstance(raw, dict) else []
            if len(trace) > 1 or any("主数据源不可用" in str(item) for item in warnings):
                fallback_count += 1

        diagnostic_rows = rows[:12]
        diagnostic_text = " ".join(
            " ".join(
                str(row.get(key) or "")
                for key in ("error_type", "error_message", "raw_payload_json")
            )
            for row in diagnostic_rows
        ).lower()
        rate_tokens = (
            "rate limit",
            "too many requests",
            "429",
            "访问频率",
            "频率限制",
            "限流",
            "每分钟",
        )
        network_tokens = (
            "timeout",
            "timed out",
            "connectionerror",
            "connection reset",
            "connection aborted",
            "连接超时",
            "连接失败",
            "远程主机",
            "network",
            "proxyerror",
            "sslerror",
        )
        has_rate_limit = any(token in diagnostic_text for token in rate_tokens)
        has_network_issue = any(token in diagnostic_text for token in network_tokens)
        recent_three_ok = bool(rows[:3]) and all(
            str(row.get("fetch_status")) in {"SUCCESS", "EMPTY"}
            for row in rows[:3]
        )
        had_nearby_problem = any(
            str(row.get("fetch_status")) in {"ERROR", "SCHEMA_ERROR"}
            for row in rows[3:16]
        )

        status = "HEALTHY"
        label = "数据源响应正常"
        message = "最近请求持续返回，筛选正在推进。"
        severity = "ok"
        if idle_seconds is not None and idle_seconds >= 180:
            status, label, severity = "STALLED", "长时间无进展", "error"
            message = "超过 3 分钟没有新数据，可能受网络或数据源限制，请留意任务状态。"
        elif has_rate_limit:
            status, label, severity = "RATE_LIMITED", "检测到频率限制", "warning"
            message = "数据源返回限流信号，任务可能正在等待或尝试备用来源。"
        elif has_network_issue:
            status, label, severity = "NETWORK_ISSUE", "检测到网络异常", "warning"
            message = "近期出现超时或连接错误，任务会继续尝试可用数据源。"
        elif idle_seconds is not None and idle_seconds >= 60:
            status, label, severity = "WAITING", "正在等待数据源", "warning"
            message = "超过 1 分钟没有新数据，可能正在等待慢请求返回。"
        elif (
            recent_three_ok
            and had_nearby_problem
            and len(errors) <= 2
            and fallback_count <= 2
        ):
            status, label, severity = "RECOVERED", "数据源已恢复", "ok"
            message = "近期异常后已连续获得成功响应，筛选继续运行。"
        elif errors or fallback_count:
            status, label, severity = "DEGRADED", "数据源降级运行", "warning"
            message = (
                f"最近 {len(rows)} 次请求中有 {len(errors)} 次失败、"
                f"{fallback_count} 次切换备用来源；失败字段将保持数据异常状态。"
            )

        last_error = errors[0] if errors else None
        return {
            "status": status,
            "label": label,
            "message": message,
            "severity": severity,
            "idle_seconds": idle_seconds,
            "last_activity_at": latest_at.isoformat() if latest_at else None,
            "recent_error_count": len(errors),
            "sample_size": len(rows),
            "fallback_count": fallback_count,
            "last_error": (
                {
                    "symbol": last_error.get("symbol"),
                    "field_group": last_error.get("field_group"),
                    "provider": last_error.get("provider"),
                    "error_type": last_error.get("error_type"),
                    "message": last_error.get("error_message"),
                    "at": last_error.get("fetched_at"),
                }
                if last_error
                else None
            ),
        }

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone().replace(tzinfo=None)
            return parsed
        except ValueError:
            return None

    def _candidates(
        self, connection: sqlite3.Connection, run_id: str, tables: set[str]
    ) -> list[dict[str, Any]]:
        if "tier1_decisions" not in tables:
            return []
        rows = connection.execute(
            """
            SELECT * FROM tier1_decisions
            WHERE run_id=? ORDER BY
                CASE screen_status WHEN 'PASS' THEN 0 WHEN 'REVIEW' THEN 1
                     WHEN 'PENDING_DATA' THEN 2 ELSE 3 END,
                symbol
            """,
            (run_id,),
        ).fetchall()
        tier2 = self._latest_tier2(connection, run_id, tables)
        tier3 = self._latest_tier3(connection, run_id, tables)
        results: list[dict[str, Any]] = []
        for raw in rows:
            row = dict(raw)
            symbol = str(row["symbol"])
            t2 = tier2.get(symbol, {})
            t3 = tier3.get(symbol, {})
            candidate = {
                "symbol": symbol,
                "stock_name": row["stock_name"],
                "screen_status": row["screen_status"],
                "business_status": row["business_status"],
                "data_status": row["data_status"],
                "pe_ttm": row["selected_pe_ttm"],
                "supplier_pe_ttm": row["supplier_pe_ttm"],
                "self_pe_ttm": row["self_pe_ttm"],
                "dividend_yield": row["dividend_yield_ttm"],
                "risk_warning": bool(row["risk_warning"]),
                "quarters": _json(row["trend_quarters_json"], []),
                "revenue_yoy": _json(row["revenue_yoy_sequence_json"], []),
                "profit_yoy": _json(row["parent_np_yoy_sequence_json"], []),
                "failed_conditions": _json(row["failed_conditions_json"], []),
                "pending_fields": _json(row["pending_fields_json"], []),
                "error_fields": _json(row["error_fields_json"], []),
                "quality_warnings": _json(row["quality_warnings_json"], []),
                "secondary_queues": _json(row["secondary_queues_json"], []),
                "stage_b_status": self._stage_b_status(row, t2),
                "stage_b": t2,
                "stage_c_status": self._stage_c_status(row, t2, t3),
                "stage_c": t3,
            }
            results.append(candidate)
        return results

    @staticmethod
    def _latest_tier2(
        connection: sqlite3.Connection, run_id: str, tables: set[str]
    ) -> dict[str, dict[str, Any]]:
        required = {"tier2_evidence_packages", "ai_assessments", "human_reviews"}
        if not required.issubset(tables):
            return {}
        rows = connection.execute(
            """
            WITH latest_package AS (
                SELECT p.* FROM tier2_evidence_packages p
                WHERE p.run_id=? AND p.rowid=(
                    SELECT p2.rowid FROM tier2_evidence_packages p2
                    WHERE p2.run_id=p.run_id AND p2.symbol=p.symbol
                    ORDER BY p2.created_at DESC, p2.rowid DESC LIMIT 1)
            ), latest_ai AS (
                SELECT a.* FROM ai_assessments a
                WHERE a.run_id=? AND a.rowid=(
                    SELECT a2.rowid FROM ai_assessments a2
                    WHERE a2.run_id=a.run_id AND a2.symbol=a.symbol
                    ORDER BY a2.imported_at DESC, a2.rowid DESC LIMIT 1)
            ), latest_review AS (
                SELECT h.* FROM human_reviews h
                WHERE h.run_id=? AND h.rowid=(
                    SELECT h2.rowid FROM human_reviews h2
                    WHERE h2.run_id=h.run_id AND h2.symbol=h.symbol
                    ORDER BY h2.reviewed_at DESC, h2.rowid DESC LIMIT 1)
            )
            SELECT p.symbol, p.package_id, p.coverage_status, p.missing_sections_json,
                   a.assessment_id, a.ai_recommendation, a.system_recommendation,
                   h.decision AS human_decision, h.reviewer, h.rationale, h.reviewed_at
            FROM latest_package p
            LEFT JOIN latest_ai a ON a.package_id=p.package_id
            LEFT JOIN latest_review h ON h.assessment_id=a.assessment_id
            """,
            (run_id, run_id, run_id),
        ).fetchall()
        result = {}
        for raw in rows:
            row = dict(raw)
            row["missing_sections"] = _json(row.pop("missing_sections_json"), [])
            result[str(row["symbol"])] = row
        return result

    @staticmethod
    def _latest_tier3(
        connection: sqlite3.Connection, run_id: str, tables: set[str]
    ) -> dict[str, dict[str, Any]]:
        required = {"tier3_risk_assessments", "tier3_human_reviews"}
        if not required.issubset(tables):
            return {}
        rows = connection.execute(
            """
            WITH latest_assessment AS (
                SELECT a.* FROM tier3_risk_assessments a
                WHERE a.run_id=? AND a.rowid=(
                    SELECT a2.rowid FROM tier3_risk_assessments a2
                    WHERE a2.run_id=a.run_id AND a2.symbol=a.symbol
                    ORDER BY a2.created_at DESC, a2.rowid DESC LIMIT 1)
            ), latest_review AS (
                SELECT h.* FROM tier3_human_reviews h
                WHERE h.run_id=? AND h.rowid=(
                    SELECT h2.rowid FROM tier3_human_reviews h2
                    WHERE h2.run_id=h.run_id AND h2.symbol=h.symbol
                    ORDER BY h2.reviewed_at DESC, h2.rowid DESC LIMIT 1)
            )
            SELECT a.symbol, a.risk_assessment_id, a.system_status, a.data_status,
                   a.industry_model, a.hard_vetoes_json, a.risk_warnings_json,
                   a.value_trap_signals_json, a.unknown_checks_json,
                   h.decision AS human_decision, h.reviewer,
                   h.rationale, h.reviewed_at
            FROM latest_assessment a
            LEFT JOIN latest_review h ON h.risk_assessment_id=a.risk_assessment_id
            """,
            (run_id, run_id),
        ).fetchall()
        result = {}
        for raw in rows:
            row = dict(raw)
            for source, target in (
                ("hard_vetoes_json", "hard_vetoes"),
                ("risk_warnings_json", "risk_warnings"),
                ("value_trap_signals_json", "value_trap_signals"),
                ("unknown_checks_json", "unknown_checks"),
            ):
                row[target] = _json(row.pop(source), [])
            result[str(row["symbol"])] = row
        return result

    @staticmethod
    def _stage_b_status(tier1: dict[str, Any], tier2: dict[str, Any]) -> str:
        if tier1["screen_status"] != "PASS":
            return "未进入"
        if not tier2:
            return "待生成证据包"
        if not tier2.get("assessment_id"):
            return "待AI研究"
        if not tier2.get("human_decision"):
            return "待人工复核"
        return str(tier2["human_decision"])

    @staticmethod
    def _stage_c_status(
        tier1: dict[str, Any], tier2: dict[str, Any], tier3: dict[str, Any]
    ) -> str:
        if tier1["screen_status"] != "PASS" or tier2.get("human_decision") != "PASS":
            return "未进入"
        if not tier3:
            return "待风险研究"
        if not tier3.get("human_decision"):
            return "待人工复核"
        return str(tier3["human_decision"])

    @staticmethod
    def _quality(
        connection: sqlite3.Connection, run_id: str, tables: set[str]
    ) -> dict[str, Any]:
        if "data_quality_assessments" not in tables:
            return {"items": [], "providers": [], "gate_passed": None}
        rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT symbol, field_group, provider, capability,
                       verification_status, severity, blocking, issues_json, assessed_at
                FROM data_quality_assessments WHERE run_id=? ORDER BY id DESC
                """,
                (run_id,),
            ).fetchall()
        ]
        for row in rows:
            row["issues"] = _json(row.pop("issues_json"), [])
            row["blocking"] = bool(row["blocking"])
        providers = sorted({str(row["provider"]) for row in rows})
        return {
            "items": rows,
            "providers": providers,
            "gate_passed": not any(row["blocking"] for row in rows),
            "blocking_count": sum(row["blocking"] for row in rows),
            "warning_count": sum(row["severity"] not in {"INFO"} for row in rows),
        }

    @staticmethod
    def _activity(
        connection: sqlite3.Connection, run_id: str, tables: set[str]
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if "human_reviews" in tables:
            for row in connection.execute(
                """SELECT symbol, decision, reviewer, reviewed_at FROM human_reviews
                   WHERE run_id=? ORDER BY reviewed_at DESC LIMIT 8""",
                (run_id,),
            ).fetchall():
                events.append(
                    {
                        "type": "review",
                        "title": f"{row['symbol']} 完成 Stage B 复核",
                        "detail": f"{row['reviewer']} · {row['decision']}",
                        "time": row["reviewed_at"],
                    }
                )
        if "tier3_human_reviews" in tables:
            for row in connection.execute(
                """SELECT symbol, decision, reviewer, reviewed_at
                   FROM tier3_human_reviews WHERE run_id=?
                   ORDER BY reviewed_at DESC LIMIT 8""",
                (run_id,),
            ).fetchall():
                events.append(
                    {
                        "type": "review",
                        "title": f"{row['symbol']} 完成 Stage C 终审",
                        "detail": f"{row['reviewer']} · {row['decision']}",
                        "time": row["reviewed_at"],
                    }
                )
        events.sort(key=lambda item: str(item["time"]), reverse=True)
        return events[:8]

    @staticmethod
    def _next_action(run: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, str]:
        recovery = (run.get("progress") or {}).get("recovery") or {}
        if recovery.get("can_resume"):
            return {
                "key": "resume-tier1",
                "title": "从 Stage A 断点继续",
                "detail": (
                    f"将跳过已完成标的，继续处理 "
                    f"{recovery.get('unfinished_count', 0)} 只未完成股票。"
                ),
            }
        if recovery.get("can_retry_data"):
            return {
                "key": "retry-tier1-data",
                "title": "补跑 Stage A 数据缺口",
                "detail": (
                    f"有 {recovery.get('data_gap_count', 0)} 只股票未产生有效决策"
                    "或处于数据异常状态。"
                ),
            }
        if run.get("status") not in {"FINISHED", "FINISHED_WITH_ERRORS"}:
            return {"key": "wait", "title": "Stage A 正在运行", "detail": "完成后可继续证据研究。"}
        passed = [row for row in candidates if row["screen_status"] == "PASS"]
        if not passed:
            return {"key": "complete", "title": "本次没有通过硬筛的候选", "detail": "可查看失败条件，或启动新的点时筛选。"}
        waiting_package = [row for row in passed if row["stage_b_status"] == "待生成证据包"]
        if waiting_package:
            return {"key": "export-tier2", "title": f"为 {len(waiting_package)} 只候选生成证据包", "detail": "进入 Stage B 前，先固化可复核证据与来源快照。"}
        if any(row["stage_b_status"] == "待AI研究" for row in passed):
            return {"key": "import-tier2", "title": "等待 Stage B 研究结果", "detail": "完成研究 JSON 后，通过 CLI 校验并导入。"}
        if any(row["stage_b_status"] == "待人工复核" for row in passed):
            return {"key": "review-tier2", "title": "处理 Stage B 人工复核", "detail": "人工结论只能维持或下调系统建议。"}
        stage_b_pass = [row for row in passed if row["stage_b_status"] == "PASS"]
        if any(row["stage_c_status"] == "待风险研究" for row in stage_b_pass):
            return {"key": "tier3", "title": "准备 Stage C 行业化风险研究", "detail": "补充行业分类后导出风险研究模板。"}
        if any(row["stage_c_status"] == "待人工复核" for row in stage_b_pass):
            return {"key": "review-tier3", "title": "处理 Stage C 人工终审", "detail": "复核硬否决、风险警告与价值陷阱信号。"}
        return {"key": "complete", "title": "本次工作流已完成", "detail": "所有可进入候选均已形成最终状态。"}

    @staticmethod
    def _empty_overview(runs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {
            "runs": runs or [],
            "run": None,
            "summary": {"universe": 0, "stage_a_pass": 0, "stage_b_pass": 0, "stage_c_pass": 0, "pending_review": 0, "screen_status_counts": {}},
            "pipeline": [],
            "candidates": [],
            "quality": {"items": [], "providers": [], "gate_passed": None, "blocking_count": 0, "warning_count": 0},
            "activity": [],
            "next_action": {"key": "new", "title": "启动第一次筛选", "detail": "输入筛选日期与股票代码开始。"},
        }
