"""Read model for the golden-pit three-phase strategy.

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


def _tier2_assessment_view(value: Any) -> dict[str, Any] | None:
    """Project validated Tier2 JSON into a browser-safe research read model."""

    assessment = _json(value, {})
    if not isinstance(assessment, dict) or not assessment:
        return None

    dimensions = []
    for item in assessment.get("dimensions", []):
        if not isinstance(item, dict):
            continue
        sources = []
        for source in item.get("sources", []):
            if not isinstance(source, dict):
                continue
            # Do not expose immutable local paths, hashes or full evidence excerpts
            # to the browser.  The import boundary has already verified those fields.
            sources.append(
                {
                    "title": source.get("title"),
                    "publisher": source.get("publisher"),
                    "date": source.get("date"),
                    "page_or_section": source.get("page_or_section"),
                }
            )
        dimensions.append(
            {
                "dimension": item.get("dimension"),
                "verdict": item.get("verdict"),
                "confidence": item.get("confidence"),
                "facts": item.get("facts", []),
                "inferences": item.get("inferences", []),
                "counter_evidence": item.get("counter_evidence", []),
                "reasoning_summary": item.get("reasoning_summary"),
                "falsification_conditions": item.get(
                    "falsification_conditions", []
                ),
                "sources": sources,
            }
        )

    return {
        "schema_version": assessment.get("schema_version"),
        "ai_provider": assessment.get("ai_provider"),
        "ai_model": assessment.get("ai_model"),
        "recommendation": assessment.get("recommendation"),
        "dimensions": dimensions,
        "scenario_analysis": assessment.get("scenario_analysis", []),
        "overall_reasoning": assessment.get("overall_reasoning"),
        "overall_counter_evidence": assessment.get(
            "overall_counter_evidence", []
        ),
        "falsification_conditions": assessment.get(
            "falsification_conditions", []
        ),
    }


class GoldenPitReadModel:
    """Project formal golden-pit workflow tables into strategy-owned views."""

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

    def overview(
        self, run_id: str | None = None, *, compact: bool = False
    ) -> dict[str, Any]:
        with self.connect() as connection:
            tables = self._tables(connection)
            if "screening_runs" not in tables:
                return self._empty_overview()

            superseded_select = (
                "CASE WHEN EXISTS(SELECT 1 FROM tier1_decision_supersessions s "
                "WHERE s.old_run_id=screening_runs.run_id) THEN 1 ELSE 0 END"
                if "tier1_decision_supersessions" in tables
                else "0"
            )
            runs = [
                dict(row)
                for row in connection.execute(
                    f"""
                    SELECT run_id, as_of_date, status, started_at, finished_at,
                           universe_size, calculation_version,
                           {superseded_select} AS superseded
                    FROM screening_runs
                    WHERE strategy_id='golden-pit'
                    ORDER BY started_at DESC, rowid DESC LIMIT 30
                    """
                ).fetchall()
            ]
            self._apply_manual_control_state(connection, runs, tables)
            self._add_run_progress(connection, runs, tables)
            selected_id = run_id or (runs[0]["run_id"] if runs else None)
            if selected_id is None:
                return self._empty_overview(runs)

            run_row = connection.execute(
                "SELECT * FROM screening_runs WHERE run_id=? AND strategy_id='golden-pit'",
                (selected_id,),
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

            if compact:
                candidate_page = self._candidate_page(
                    connection, selected_id, tables, page=1, page_size=5
                )
                candidates = candidate_page["items"]
                candidate_summary = candidate_page["summary"]
            else:
                candidates = self._candidates(connection, selected_id, tables)
                candidate_summary = self._candidate_summary(candidates)
            quality = self._quality(
                connection, selected_id, tables, item_limit=0 if compact else None
            )
            activity = self._activity(connection, selected_id, tables)
            counts = candidate_summary["screen_status_counts"]
            stage_a_pass = candidate_summary["stage_a_pass"]
            stage_b_pass = candidate_summary["stage_b_pass"]
            stage_c_pass = candidate_summary["stage_c_pass"]
            pending_review = candidate_summary["pending_review"]
            candidate_total = candidate_summary["total"]
            next_action = self._next_action_from_summary(run, candidate_summary)
            return {
                "runs": runs,
                "run": run,
                "summary": {
                    "universe": (
                        run.get("universe_size")
                        or (run.get("progress") or {}).get("total")
                        or candidate_total
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
                        "name": "量化初筛",
                        "caption": "估值 · 分红 · 连续两季正增长 · 风险警示",
                        "total": candidate_total,
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
                "candidate_total": candidate_total,
                "quality": quality,
                "activity": activity,
                "next_action": next_action,
            }

    def catalog_snapshot(self) -> dict[str, Any]:
        """Return only the latest run and aggregate metrics for strategy cards."""
        overview = self.overview(compact=True)
        return {"run": overview["run"], "summary": overview["summary"]}

    def candidates_page(
        self,
        run_id: str,
        *,
        page: int = 1,
        page_size: int = 100,
        query: str = "",
        filters: dict[str, str] | None = None,
        sort_key: str | None = None,
        sort_direction: str = "asc",
    ) -> dict[str, Any]:
        with self.connect() as connection:
            tables = self._tables(connection)
            return self._candidate_page(
                connection,
                run_id,
                tables,
                page=page,
                page_size=page_size,
                query=query,
                filters=filters,
                sort_key=sort_key,
                sort_direction=sort_direction,
            )

    def quality_page(
        self, run_id: str, *, page: int = 1, page_size: int = 200
    ) -> dict[str, Any]:
        page = max(1, page)
        page_size = max(1, min(500, page_size))
        with self.connect() as connection:
            tables = self._tables(connection)
            result = self._quality(
                connection,
                run_id,
                tables,
                item_limit=page_size,
                item_offset=(page - 1) * page_size,
            )
        result.update({"page": page, "page_size": page_size})
        return result

    def running_runs(self) -> list[dict[str, Any]]:
        """Return live quantitative-screening runs with database-backed progress."""
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
                    FROM screening_runs
                    WHERE strategy_id='golden-pit' AND status='RUNNING'
                    ORDER BY started_at DESC, rowid DESC
                    """
                ).fetchall()
            ]
            self._apply_manual_control_state(connection, runs, tables)
            self._add_run_progress(connection, runs, tables)
            return runs

    @staticmethod
    def _apply_manual_control_state(
        connection: sqlite3.Connection,
        runs: list[dict[str, Any]],
        tables: set[str],
    ) -> None:
        if "screening_run_control_events" not in tables:
            return
        latest = {
            str(row["run_id"]): dict(row)
            for row in connection.execute(
                """
                SELECT event_id, run_id, action, actor, reason, previous_status,
                       target_status, worker_process_id, created_at
                FROM screening_run_control_events e
                WHERE created_at=(
                    SELECT MAX(e2.created_at) FROM screening_run_control_events e2
                    WHERE e2.run_id=e.run_id
                )
                """
            ).fetchall()
        }
        for run in runs:
            run["manual_control"] = latest.get(str(run["run_id"]))

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

            started = GoldenPitReadModel._parse_datetime(run.get("started_at"))
            elapsed = max(0, int((now - started).total_seconds())) if started else None
            seconds_per_item = None
            first = GoldenPitReadModel._parse_datetime(stats.get("first_completed_at"))
            last = GoldenPitReadModel._parse_datetime(stats.get("last_completed_at"))
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
                GoldenPitReadModel._source_health(connection, run_id, now, started)
                if status == "RUNNING" and "source_observations" in tables
                else None
            )
            recovery = GoldenPitReadModel._recovery_status(
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
                expiry = GoldenPitReadModel._parse_datetime(lease["lease_expires_at"])
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
        latest_at = GoldenPitReadModel._parse_datetime(
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

    @staticmethod
    def _candidate_summary(candidates: list[dict[str, Any]]) -> dict[str, Any]:
        counts = Counter(row["screen_status"] for row in candidates)
        stage_b_counts = Counter(row["stage_b_status"] for row in candidates)
        stage_c_counts = Counter(row["stage_c_status"] for row in candidates)
        return {
            "total": len(candidates),
            "stage_a_pass": sum(
                row["screen_status"] == "PASS" for row in candidates
            ),
            "stage_b_pass": sum(
                row["stage_b_status"] == "PASS" for row in candidates
            ),
            "stage_c_pass": sum(
                row["stage_c_status"] == "PASS" for row in candidates
            ),
            "pending_review": sum(
                row["stage_b_status"] == "待人工复核"
                or row["stage_c_status"] == "待人工复核"
                for row in candidates
            ),
            "screen_status_counts": dict(counts),
            "stage_b_status_counts": dict(stage_b_counts),
            "stage_c_status_counts": dict(stage_c_counts),
        }

    def _candidate_index(
        self, connection: sqlite3.Connection, run_id: str, tables: set[str]
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        if "tier1_decisions" not in tables:
            return [], {}, {}
        tier2 = self._latest_tier2(connection, run_id, tables)
        tier3 = self._latest_tier3(connection, run_id, tables)
        rows = connection.execute(
            """
            SELECT d.symbol, d.stock_name, d.screen_status, d.business_status, d.data_status,
                   d.selected_pe_ttm AS pe_ttm,
                   COALESCE(d.latest_fiscal_year_dividend_yield,
                            d.dividend_yield_ttm) AS dividend_yield,
                   CASE WHEN s.old_decision_id IS NULL THEN 1 ELSE 0 END AS is_valid,
                   s.new_run_id AS superseded_by_run_id
            FROM tier1_decisions d
            LEFT JOIN tier1_decision_supersessions s
              ON s.old_decision_id=d.decision_id
            WHERE d.run_id=?
            """,
            (run_id,),
        ).fetchall()
        index: list[dict[str, Any]] = []
        for raw in rows:
            item = dict(raw)
            if not item["is_valid"]:
                item["screen_status"] = "SUPERSEDED"
            symbol = str(item["symbol"])
            item["stage_b_status"] = self._stage_b_status(
                item, tier2.get(symbol, {})
            )
            item["stage_c_status"] = self._stage_c_status(
                item, tier2.get(symbol, {}), tier3.get(symbol, {})
            )
            index.append(item)
        return index, tier2, tier3

    @staticmethod
    def _range_matches(value: Any, selected: str, kind: str) -> bool:
        if selected == "ALL":
            return True
        present = value is not None
        if selected == "MISSING":
            return not present
        if not present:
            return False
        numeric = float(value)
        if kind == "pe":
            return {
                "LT15": numeric < 15,
                "15TO30": 15 <= numeric < 30,
                "GTE30": numeric >= 30,
            }.get(selected, True)
        return {
            "GT5": numeric > 0.05,
            "2TO5": 0.02 <= numeric <= 0.05,
            "LT2": numeric < 0.02,
        }.get(selected, True)

    def _candidate_page(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        tables: set[str],
        *,
        page: int,
        page_size: int,
        query: str = "",
        filters: dict[str, str] | None = None,
        sort_key: str | None = None,
        sort_direction: str = "asc",
    ) -> dict[str, Any]:
        page = max(1, page)
        page_size = max(1, min(500, page_size))
        filters = filters or {}
        index, tier2, tier3 = self._candidate_index(connection, run_id, tables)
        summary = self._candidate_summary(index)
        normalized_query = query.strip().lower()
        filtered = [
            item
            for item in index
            if (
                not normalized_query
                or normalized_query in str(item["symbol"]).lower()
                or normalized_query in str(item["stock_name"]).lower()
            )
            and (
                filters.get("stageA", "ALL") == "ALL"
                or item["screen_status"] == filters.get("stageA")
            )
            and (
                filters.get("data", "ALL") == "ALL"
                or item["data_status"] == filters.get("data")
            )
            and self._range_matches(
                item.get("pe_ttm"), filters.get("pe", "ALL"), "pe"
            )
            and self._range_matches(
                item.get("dividend_yield"),
                filters.get("dividend", "ALL"),
                "dividend",
            )
            and (
                filters.get("stageB", "ALL") == "ALL"
                or item["stage_b_status"] == filters.get("stageB")
            )
            and (
                filters.get("stageC", "ALL") == "ALL"
                or item["stage_c_status"] == filters.get("stageC")
            )
        ]
        if sort_key in {"pe_ttm", "dividend_yield"}:
            reverse = sort_direction == "desc"
            present = [item for item in filtered if item.get(sort_key) is not None]
            missing = [item for item in filtered if item.get(sort_key) is None]
            present.sort(
                key=lambda item: (float(item[sort_key]), str(item["symbol"])),
                reverse=reverse,
            )
            filtered = present + sorted(missing, key=lambda item: str(item["symbol"]))
        else:
            rank = {"PASS": 0, "REVIEW": 1, "PENDING_DATA": 2}
            filtered.sort(
                key=lambda item: (
                    rank.get(str(item["screen_status"]), 3),
                    str(item["symbol"]),
                )
            )
        total = len(filtered)
        start = (page - 1) * page_size
        selected = filtered[start : start + page_size]
        symbols = [str(item["symbol"]) for item in selected]
        details = self._candidates(
            connection,
            run_id,
            tables,
            symbols=symbols,
            tier2=tier2,
            tier3=tier3,
        )
        by_symbol = {item["symbol"]: item for item in details}
        return {
            "items": [by_symbol[symbol] for symbol in symbols if symbol in by_symbol],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": max(1, (total + page_size - 1) // page_size),
            "facets": {
                "stage_b": sorted({item["stage_b_status"] for item in index}),
                "stage_c": sorted({item["stage_c_status"] for item in index}),
            },
            "summary": summary,
        }

    def _candidates(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        tables: set[str],
        *,
        symbols: list[str] | None = None,
        tier2: dict[str, dict[str, Any]] | None = None,
        tier3: dict[str, dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        if "tier1_decisions" not in tables:
            return []
        if symbols == []:
            return []
        symbol_clause = ""
        parameters: list[Any] = [run_id]
        if symbols is not None:
            symbol_clause = f" AND d.symbol IN ({','.join('?' for _ in symbols)})"
            parameters.extend(symbols)
        rows = connection.execute(
            f"""
            SELECT d.*, CASE WHEN s.old_decision_id IS NULL THEN 1 ELSE 0 END AS is_valid,
                   s.new_run_id AS superseded_by_run_id
            FROM tier1_decisions d
            LEFT JOIN tier1_decision_supersessions s
              ON s.old_decision_id=d.decision_id
            WHERE d.run_id=?{symbol_clause} ORDER BY
                CASE d.screen_status WHEN 'PASS' THEN 0 WHEN 'REVIEW' THEN 1
                     WHEN 'PENDING_DATA' THEN 2 ELSE 3 END,
                d.symbol
            """,
            parameters,
        ).fetchall()
        tier2 = tier2 if tier2 is not None else self._latest_tier2(
            connection, run_id, tables
        )
        tier3 = tier3 if tier3 is not None else self._latest_tier3(
            connection, run_id, tables
        )
        results: list[dict[str, Any]] = []
        for raw in rows:
            row = dict(raw)
            effective_screen_status = (
                row["screen_status"] if row["is_valid"] else "SUPERSEDED"
            )
            symbol = str(row["symbol"])
            t2 = tier2.get(symbol, {})
            t3 = tier3.get(symbol, {})
            candidate = {
                "symbol": symbol,
                "stock_name": row["stock_name"],
                "screen_status": effective_screen_status,
                "historical_screen_status": row["screen_status"],
                "is_valid": bool(row["is_valid"]),
                "superseded_by_run_id": row.get("superseded_by_run_id"),
                "business_status": row["business_status"],
                "data_status": row["data_status"],
                "pe_ttm": row["selected_pe_ttm"],
                "supplier_pe_ttm": row["supplier_pe_ttm"],
                "self_pe_ttm": row["self_pe_ttm"],
                "dividend_yield": (
                    row.get("latest_fiscal_year_dividend_yield")
                    if row.get("latest_fiscal_year_dividend_yield") is not None
                    else row["dividend_yield_ttm"]
                ),
                "latest_fiscal_year": row.get("latest_fiscal_year"),
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
                   a.assessment_id, a.ai_provider, a.ai_model, a.imported_at,
                   a.ai_recommendation, a.system_recommendation, a.assessment_json,
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
            row["assessment"] = _tier2_assessment_view(
                row.pop("assessment_json", None)
            )
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
        if tier1.get("is_valid") in {0, False} or tier1.get("screen_status") == "SUPERSEDED":
            return "已失效"
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
        if tier1.get("is_valid") in {0, False} or tier1.get("screen_status") == "SUPERSEDED":
            return "已失效"
        if tier1["screen_status"] != "PASS" or tier2.get("human_decision") != "PASS":
            return "未进入"
        if not tier3:
            return "待风险研究"
        if not tier3.get("human_decision"):
            return "待人工复核"
        return str(tier3["human_decision"])

    @staticmethod
    def _quality(
        connection: sqlite3.Connection,
        run_id: str,
        tables: set[str],
        *,
        item_limit: int | None = None,
        item_offset: int = 0,
    ) -> dict[str, Any]:
        if "data_quality_assessments" not in tables:
            return {
                "items": [],
                "providers": [],
                "gate_passed": None,
                "total": 0,
                "blocking_count": 0,
                "warning_count": 0,
            }
        aggregate = connection.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN blocking=1 THEN 1 ELSE 0 END) AS blocking_count,
                   SUM(CASE WHEN severity!='INFO' THEN 1 ELSE 0 END) AS warning_count
            FROM data_quality_assessments WHERE run_id=?
            """,
            (run_id,),
        ).fetchone()
        query = """
            SELECT symbol, field_group, provider, capability,
                   verification_status, severity, blocking, issues_json, assessed_at
            FROM data_quality_assessments WHERE run_id=? ORDER BY id DESC
        """
        parameters: list[Any] = [run_id]
        if item_limit is not None:
            query += " LIMIT ? OFFSET ?"
            parameters.extend([item_limit, max(0, item_offset)])
        rows = [
            dict(row)
            for row in connection.execute(query, parameters).fetchall()
        ]
        for row in rows:
            row["issues"] = _json(row.pop("issues_json"), [])
            row["blocking"] = bool(row["blocking"])
        providers = [
            str(row[0])
            for row in connection.execute(
                """
                SELECT DISTINCT provider FROM data_quality_assessments
                WHERE run_id=? ORDER BY provider
                """,
                (run_id,),
            ).fetchall()
        ]
        total = int(aggregate["total"] or 0)
        blocking_count = int(aggregate["blocking_count"] or 0)
        warning_count = int(aggregate["warning_count"] or 0)
        return {
            "items": rows,
            "providers": providers,
            "gate_passed": not bool(blocking_count),
            "total": total,
            "blocking_count": blocking_count,
            "warning_count": warning_count,
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
                        "title": f"{row['symbol']} 完成证据研究复核",
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
                        "title": f"{row['symbol']} 完成风险终审",
                        "detail": f"{row['reviewer']} · {row['decision']}",
                        "time": row["reviewed_at"],
                    }
                )
        events.sort(key=lambda item: str(item["time"]), reverse=True)
        return events[:8]

    @staticmethod
    def _next_action_from_summary(
        run: dict[str, Any], summary: dict[str, Any]
    ) -> dict[str, str]:
        recovery = (run.get("progress") or {}).get("recovery") or {}
        if recovery.get("can_resume"):
            return {
                "key": "resume-tier1",
                "title": "从量化初筛断点继续",
                "detail": (
                    f"将跳过已完成标的，继续处理 "
                    f"{recovery.get('unfinished_count', 0)} 只未完成股票。"
                ),
            }
        if recovery.get("can_retry_data"):
            return {
                "key": "retry-tier1-data",
                "title": "补跑量化初筛数据缺口",
                "detail": (
                    f"有 {recovery.get('data_gap_count', 0)} 只股票未产生有效决策"
                    "或处于数据异常状态。"
                ),
            }
        if run.get("status") not in {"FINISHED", "FINISHED_WITH_ERRORS"}:
            return {
                "key": "wait",
                "title": "量化初筛正在运行",
                "detail": "完成后可继续证据研究。",
            }
        if not summary.get("stage_a_pass"):
            return {
                "key": "complete",
                "title": "本次没有通过硬筛的候选",
                "detail": "可查看失败条件，或启动新的点时筛选。",
            }
        stage_b = summary.get("stage_b_status_counts", {})
        stage_c = summary.get("stage_c_status_counts", {})
        if stage_b.get("待生成证据包"):
            count = stage_b["待生成证据包"]
            return {
                "key": "export-tier2",
                "title": f"为 {count} 只候选生成证据包",
                "detail": "进入证据研究前，先固化可复核证据与来源快照。",
            }
        if stage_b.get("待AI研究"):
            return {"key": "import-tier2", "title": "等待证据研究结果", "detail": "完成研究 JSON 后，通过 CLI 校验并导入。"}
        if stage_b.get("待人工复核"):
            return {"key": "review-tier2", "title": "处理证据研究人工复核", "detail": "人工结论只能维持或下调系统建议。"}
        if stage_c.get("待风险研究"):
            return {"key": "tier3", "title": "准备行业化风险终审", "detail": "补充行业分类后导出风险研究模板。"}
        if stage_c.get("待人工复核"):
            return {"key": "review-tier3", "title": "处理风险终审人工复核", "detail": "复核硬否决、风险警告与价值陷阱信号。"}
        return {"key": "complete", "title": "本次工作流已完成", "detail": "所有可进入候选均已形成最终状态。"}

    @staticmethod
    def _next_action(run: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, str]:
        recovery = (run.get("progress") or {}).get("recovery") or {}
        if recovery.get("can_resume"):
            return {
                "key": "resume-tier1",
                "title": "从量化初筛断点继续",
                "detail": (
                    f"将跳过已完成标的，继续处理 "
                    f"{recovery.get('unfinished_count', 0)} 只未完成股票。"
                ),
            }
        if recovery.get("can_retry_data"):
            return {
                "key": "retry-tier1-data",
                "title": "补跑量化初筛数据缺口",
                "detail": (
                    f"有 {recovery.get('data_gap_count', 0)} 只股票未产生有效决策"
                    "或处于数据异常状态。"
                ),
            }
        if run.get("status") not in {"FINISHED", "FINISHED_WITH_ERRORS"}:
            return {"key": "wait", "title": "量化初筛正在运行", "detail": "完成后可继续证据研究。"}
        passed = [row for row in candidates if row["screen_status"] == "PASS"]
        if not passed:
            return {"key": "complete", "title": "本次没有通过硬筛的候选", "detail": "可查看失败条件，或启动新的点时筛选。"}
        waiting_package = [row for row in passed if row["stage_b_status"] == "待生成证据包"]
        if waiting_package:
            return {"key": "export-tier2", "title": f"为 {len(waiting_package)} 只候选生成证据包", "detail": "进入证据研究前，先固化可复核证据与来源快照。"}
        if any(row["stage_b_status"] == "待AI研究" for row in passed):
            return {"key": "import-tier2", "title": "等待证据研究结果", "detail": "完成研究 JSON 后，通过 CLI 校验并导入。"}
        if any(row["stage_b_status"] == "待人工复核" for row in passed):
            return {"key": "review-tier2", "title": "处理证据研究人工复核", "detail": "人工结论只能维持或下调系统建议。"}
        stage_b_pass = [row for row in passed if row["stage_b_status"] == "PASS"]
        if any(row["stage_c_status"] == "待风险研究" for row in stage_b_pass):
            return {"key": "tier3", "title": "准备行业化风险终审", "detail": "补充行业分类后导出风险研究模板。"}
        if any(row["stage_c_status"] == "待人工复核" for row in stage_b_pass):
            return {"key": "review-tier3", "title": "处理风险终审人工复核", "detail": "复核硬否决、风险警告与价值陷阱信号。"}
        return {"key": "complete", "title": "本次工作流已完成", "detail": "所有可进入候选均已形成最终状态。"}

    @staticmethod
    def _empty_overview(runs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {
            "runs": runs or [],
            "run": None,
            "summary": {"universe": 0, "stage_a_pass": 0, "stage_b_pass": 0, "stage_c_pass": 0, "pending_review": 0, "screen_status_counts": {}},
            "pipeline": [],
            "candidates": [],
            "candidate_total": 0,
            "quality": {"items": [], "providers": [], "gate_passed": None, "total": 0, "blocking_count": 0, "warning_count": 0},
            "activity": [],
            "next_action": {"key": "new", "title": "启动第一次筛选", "detail": "输入筛选日期与股票代码开始。"},
        }
