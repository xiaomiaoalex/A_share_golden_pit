"""Build inspectable, point-in-time Tier2 evidence packages from Tier1 PASS rows."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from collections.abc import Iterable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from src.strategies.golden_pit.persistence.tier2_repository import Tier2Repository
from src.strategies.golden_pit.resources import EVIDENCE_PROMPT, EVIDENCE_SCHEMA

from .constants import EVIDENCE_SECTIONS, PACKAGE_VERSION, SCHEMA_VERSION


def _decode_json_fields(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for key, value in list(result.items()):
        if key.endswith("_json") and isinstance(value, str):
            try:
                result[key[:-5]] = json.loads(value)
            except json.JSONDecodeError:
                result[key[:-5]] = None
            del result[key]
    for key in ("raw_value", "calculated_value"):
        value = result.get(key)
        if isinstance(value, str):
            try:
                result[key] = json.loads(value)
            except json.JSONDecodeError:
                pass
    return result


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class Tier2EvidenceExporter:
    def __init__(self, repository: Tier2Repository, project_root: Path | None = None):
        self.repository = repository
        self.project_root = project_root or Path(__file__).resolve().parents[4]

    def export_run(
        self,
        run_id: str,
        output_dir: str | Path,
        *,
        symbols: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        candidates = self.repository.tier1_pass_candidates(run_id, symbols)
        if not candidates:
            raise ValueError("该运行没有符合条件的Tier1 PASS候选股")

        root = Path(output_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(EVIDENCE_SCHEMA, root / "tier2_ai_schema.json")
        shutil.copyfile(EVIDENCE_PROMPT, root / "tier2_ai_prompt_template.md")

        packages = []
        for decision in candidates:
            package = self.build_package(decision)
            actual_id = self.repository.save_evidence_package(package)
            package["package_id"] = actual_id
            stem = f"{package['symbol']}_{actual_id}"
            json_path = root / f"{stem}.json"
            markdown_path = root / f"{stem}.md"
            json_path.write_text(
                json.dumps(package, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            markdown_path.write_text(self.render_markdown(package), encoding="utf-8")
            self.repository.save_evidence_package(
                package,
                json_path=str(json_path),
                markdown_path=str(markdown_path),
            )
            packages.append(
                {
                    "package_id": actual_id,
                    "symbol": package["symbol"],
                    "stock_name": package["stock_name"],
                    "coverage_status": package["coverage_status"],
                    "missing_sections": package["missing_sections"],
                    "content_hash": package["content_hash"],
                    "json_path": str(json_path),
                    "markdown_path": str(markdown_path),
                }
            )

        index = {
            "run_id": run_id,
            "package_version": PACKAGE_VERSION,
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "package_count": len(packages),
            "packages": packages,
            "usage": {
                "prompt": str(root / "tier2_ai_prompt_template.md"),
                "schema": str(root / "tier2_ai_schema.json"),
                "import_command": "python main.py import-tier2 --file AI_RESULTS.json",
            },
        }
        index_path = root / "index.json"
        index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (root / "index.md").write_text(self.render_index(index), encoding="utf-8")
        index["index_path"] = str(index_path)
        return index

    def build_package(self, decision: dict[str, Any]) -> dict[str, Any]:
        run_id = str(decision["run_id"])
        symbol = str(decision["symbol"])
        point_in_time = self.repository.evidence_rows(run_id, symbol)
        normalized_decision = _decode_json_fields(decision)
        normalized = {
            key: [_decode_json_fields(row) for row in rows]
            for key, rows in point_in_time.items()
        }
        future_violations = self._future_dated_records(
            date.fromisoformat(str(decision["as_of_date"])), normalized
        )
        if future_violations:
            raise ValueError(
                f"{symbol}证据中发现as-of之后的数据，拒绝导出: "
                + ", ".join(future_violations[:5])
            )

        sections = self._sections(normalized_decision, normalized)
        missing = [
            name
            for name in EVIDENCE_SECTIONS
            if sections[name]["status"] != "AVAILABLE"
        ]
        evidence = {
            "scope": {
                "intended_use": "Tier2 SOR3.0 human-AI research",
                "grain": "one Tier1 run × one security × one as_of_date",
                "point_in_time_rule": (
                    "Only records tied to the same Tier1 run are decision-grade; "
                    "missing evidence remains explicit."
                ),
            },
            "tier1_decision": normalized_decision,
            "sections": sections,
            "raw_point_in_time_records": normalized,
            "data_quality": {
                "coverage_status": "COMPLETE" if not missing else "PARTIAL",
                "missing_sections": missing,
                "blocking_quality_issue_count": sum(
                    1
                    for item in normalized["data_quality_assessments"]
                    if bool(item.get("blocking"))
                ),
                "section_profile": {
                    "expected": len(EVIDENCE_SECTIONS),
                    "available": sum(
                        1 for item in sections.values() if item["status"] == "AVAILABLE"
                    ),
                    "partial": sum(
                        1 for item in sections.values() if item["status"] == "PARTIAL"
                    ),
                    "missing": sum(
                        1 for item in sections.values() if item["status"] == "MISSING"
                    ),
                    "available_rate": sum(
                        1 for item in sections.values() if item["status"] == "AVAILABLE"
                    )
                    / len(EVIDENCE_SECTIONS),
                },
                "future_dated_record_count": 0,
                "warning": (
                    "Legacy financial_data rows without announcement/availability dates "
                    "are deliberately excluded from decision-grade evidence."
                ),
            },
            "ai_contract": {
                "schema_version": SCHEMA_VERSION,
                "schema_file": "tier2_ai_schema.json",
                "prompt_file": "tier2_ai_prompt_template.md",
                "external_ai_call": "manual",
            },
        }
        content_hash = _canonical_hash(evidence)
        return {
            "package_id": str(uuid.uuid4()),
            "package_version": PACKAGE_VERSION,
            "run_id": run_id,
            "symbol": symbol,
            "stock_name": str(decision["stock_name"]),
            "as_of_date": str(decision["as_of_date"]),
            "content_hash": content_hash,
            "coverage_status": "COMPLETE" if not missing else "PARTIAL",
            "missing_sections": missing,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "evidence": evidence,
        }

    @staticmethod
    def _future_dated_records(
        as_of_date: date, records: dict[str, list[dict[str, Any]]]
    ) -> list[str]:
        checks = {
            "raw_financial_metrics": ("announcement_date", "available_at", "revision_at"),
            "dividend_events": ("ex_date", "announcement_date"),
            "source_lineage": ("announcement_date", "available_at"),
            "source_observations": ("available_at",),
        }
        violations = []
        for group, fields in checks.items():
            for index, item in enumerate(records[group]):
                for field in fields:
                    value = item.get(field)
                    if not value:
                        continue
                    try:
                        observed_date = date.fromisoformat(str(value)[:10])
                    except ValueError:
                        violations.append(f"{group}[{index}].{field}=INVALID_DATE")
                        continue
                    if observed_date > as_of_date:
                        violations.append(f"{group}[{index}].{field}={value}")
        return violations

    @staticmethod
    def _sections(
        decision: dict[str, Any], records: dict[str, list[dict[str, Any]]]
    ) -> dict[str, dict[str, Any]]:
        quarterly = records["quarterly_series"]
        raw_metrics = records["raw_financial_metrics"]
        dividends = records["dividend_events"]
        lineage = records["source_lineage"]
        annual_report_years = {
            str(item.get("report_period", ""))[:4]
            for item in raw_metrics
            if str(item.get("report_period", "")).endswith("-12-31")
        }

        def available(data: Any, note: str) -> dict[str, Any]:
            return {"status": "AVAILABLE", "note": note, "records": data}

        def partial(data: Any, note: str) -> dict[str, Any]:
            return {"status": "PARTIAL", "note": note, "records": data}

        def missing(note: str) -> dict[str, Any]:
            return {"status": "MISSING", "note": note, "records": []}

        sections = {
            "tier1_decision": available(
                decision, "Tier1 PASS decision and hard-filter calculations."
            ),
            "financial_history_5y": (
                available(raw_metrics, "At least five report years with point-in-time lineage.")
                if len(annual_report_years) >= 5
                else partial(
                    raw_metrics,
                    f"Only {len(annual_report_years)} point-in-time annual reports are available; five are required.",
                )
                if raw_metrics
                else missing("No point-in-time five-year financial statements." )
            ),
            "recent_quarterly_financials": (
                available(quarterly, "Single-quarter revenue and parent profit series.")
                if len(quarterly) >= 5
                else partial(quarterly, "Fewer than five comparable recent quarters.")
                if quarterly
                else missing("No single-quarter series tied to this run.")
            ),
            "profitability_and_capital_returns": missing(
                "Gross margin, net margin, ROE and ROIC with point-in-time lineage are absent."
            ),
            "cash_flow_and_capex": missing(
                "Operating cash flow, capex and free cash flow are absent."
            ),
            "dividend_sustainability": (
                partial(
                    dividends,
                    "Implemented pre-tax dividends are available, but CFO/FCF coverage is absent.",
                )
                if dividends
                else missing("No implemented dividend events or cash-flow coverage evidence.")
            ),
            "balance_sheet_and_working_capital": missing(
                "Debt, cash, receivables, inventory and contract liabilities are absent."
            ),
            "non_recurring_items": missing(
                "Non-recurring gain/loss composition is absent."
            ),
            "segment_and_region": missing(
                "Segment and geographic disclosures are absent."
            ),
            "industry_demand_and_competition": missing(
                "No sourced industry demand or competitive evidence has been attached."
            ),
            "market_share_capacity_and_capex": missing(
                "Market share, capacity and industry/company capex evidence is absent."
            ),
            "historical_valuation": missing(
                "No point-in-time historical valuation distribution is attached."
            ),
            "reverse_valuation": missing(
                "No reverse valuation assumptions or calculations are attached."
            ),
            "source_lineage": (
                available(lineage, "Field-level source and calculation lineage.")
                if lineage
                else missing("No field-level source lineage.")
            ),
        }
        return sections

    @staticmethod
    def render_markdown(package: dict[str, Any]) -> str:
        decision = package["evidence"]["tier1_decision"]
        sections = package["evidence"]["sections"]
        lines = [
            f"# {package['symbol']} {package['stock_name']} Tier2证据包",
            "",
            f"- as-of：{package['as_of_date']}",
            f"- Tier1 run：`{package['run_id']}`",
            f"- package_id：`{package['package_id']}`",
            f"- content_hash：`{package['content_hash']}`",
            f"- 证据覆盖：{package['coverage_status']}",
            "",
            "## Tier1客观候选结论",
            "",
            f"- 状态：{decision.get('screen_status')}",
            f"- PE(TTM)：{decision.get('selected_pe_ttm')}",
            f"- 股息率(TTM)：{decision.get('dividend_yield_ttm')}",
            f"- 收入同比序列：{decision.get('revenue_yoy_sequence')}",
            f"- 归母净利润同比序列：{decision.get('parent_np_yoy_sequence')}",
            "",
            "## 证据覆盖与缺口",
            "",
            "| 证据区块 | 状态 | 说明 |",
            "|---|---|---|",
        ]
        for name in EVIDENCE_SECTIONS:
            item = sections[name]
            note = str(item["note"]).replace("|", "\\|")
            lines.append(f"| {name} | {item['status']} | {note} |")
        lines.extend(
            [
                "",
                "## 研究约束",
                "",
                "使用同目录提示词和JSON Schema。缺少公告可得时间或可靠出处的内容不得当作事实；",
                "任何关键维度证据不足必须返回 `INSUFFICIENT_EVIDENCE`。原始点时记录见同名JSON。",
                "",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def render_index(index: dict[str, Any]) -> str:
        lines = [
            f"# Tier2证据包索引 — run {index['run_id']}",
            "",
            "| 股票 | 公司 | 覆盖状态 | 缺失区块数 | JSON | Markdown |",
            "|---|---|---:|---:|---|---|",
        ]
        for item in index["packages"]:
            lines.append(
                f"| {item['symbol']} | {item['stock_name']} | "
                f"{item['coverage_status']} | {len(item['missing_sections'])} | "
                f"{Path(item['json_path']).name} | {Path(item['markdown_path']).name} |"
            )
        lines.extend(
            [
                "",
                "AI结果导入前会校验Schema、七个维度、三个情景，以及证据包ID和哈希。",
                "最终进入Tier2仍需人工确认。",
                "",
            ]
        )
        return "\n".join(lines)
