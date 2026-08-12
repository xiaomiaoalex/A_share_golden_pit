"""Export per-stock Stage C risk research templates after Stage B human PASS."""

from __future__ import annotations

import json
import re
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from src.evidence import verify_sources
from src.strategies.golden_pit.persistence.tier3_repository import Tier3Repository
from src.strategies.golden_pit.resources import RISK_INPUT_SCHEMA, RISK_RULES

from .models import RiskModelRegistry


class Tier3TemplateExporter:
    schema_version = "tier3-risk-input-v1.1"

    def __init__(
        self,
        repository: Tier3Repository,
        registry: RiskModelRegistry,
        project_root: Path | None = None,
    ):
        self.repository = repository
        self.registry = registry
        self.project_root = project_root or Path(__file__).resolve().parents[4]

    def export_run(
        self,
        run_id: str,
        classifications: list[dict[str, Any]],
        output_dir: str | Path,
        classification_base_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        normalized = [self._validate_classification(item) for item in classifications]
        by_symbol = {str(item["symbol"]): item for item in normalized}
        if len(by_symbol) != len(classifications):
            raise ValueError("行业分类文件存在重复股票")
        candidates = self.repository.tier2_pass_candidates(run_id, by_symbol)
        candidate_symbols = {item["symbol"] for item in candidates}
        extra = sorted(set(by_symbol) - candidate_symbols)
        if extra:
            raise ValueError("行业分类包含非Stage B PASS股票: " + ", ".join(extra))
        if not candidates:
            raise ValueError("该运行没有可进入Stage C的Stage B人工PASS股票")

        source_root = Path(classification_base_dir or Path.cwd()).resolve()
        prepared = {}
        for candidate in candidates:
            classification = by_symbol[candidate["symbol"]]
            as_of = date.fromisoformat(candidate["as_of_date"])
            verify_sources(
                classification["sources"],
                as_of=as_of,
                base_dir=source_root,
                required_claims=[classification["rationale"]],
                context=f"{candidate['symbol']}.industry_classification",
            )
            classification = {
                **classification,
                "sources": [
                    self._absolute_source_paths(source, source_root)
                    for source in classification["sources"]
                ],
            }
            model = self.registry.get(str(classification["industry_model"]))
            tier2_assessment = json.loads(candidate["assessment_json"])
            falsification = tier2_assessment.get("falsification_conditions")
            if not isinstance(falsification, list) or len(falsification) < 3:
                raise ValueError(f"{candidate['symbol']}Stage B证伪条件不完整")
            prepared[candidate["symbol"]] = (
                classification,
                model,
                falsification,
            )

        root = Path(output_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            RISK_INPUT_SCHEMA,
            root / "tier3_risk_input_schema.json",
        )
        shutil.copyfile(
            RISK_RULES,
            root / "tier3_risk_rules.json",
        )
        exported = []
        for candidate in candidates:
            classification, model, falsification = prepared[candidate["symbol"]]
            model_code = model.model_code
            risk_input = {
                "schema_version": self.schema_version,
                "run_id": run_id,
                "symbol": candidate["symbol"],
                "as_of_date": candidate["as_of_date"],
                "tier2_review_id": candidate["tier2_review_id"],
                "industry_classification": {
                    "industry_model": model_code,
                    "industry": classification["industry"],
                    "rationale": classification["rationale"],
                    "sources": classification["sources"],
                },
                "checks": [
                    {
                        "check_id": rule.rule_id,
                        "status": "UNKNOWN",
                        "confidence": 0.0,
                        "facts": [],
                        "inferences": [],
                        "counter_evidence": [],
                        "sources": [],
                        "metrics": [],
                        "reasoning_summary": "暂无可靠证据",
                    }
                    for rule in model.rules
                ],
                "falsification_conditions": falsification,
                "overall_notes": "待Stage C风险与价值陷阱研究",
            }
            json_path = root / f"{candidate['symbol']}_tier3_risk_input.json"
            markdown_path = root / f"{candidate['symbol']}_tier3_risk_guide.md"
            json_path.write_text(
                json.dumps(risk_input, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            markdown_path.write_text(
                self.render_markdown(candidate, classification, model), encoding="utf-8"
            )
            exported.append(
                {
                    "symbol": candidate["symbol"],
                    "stock_name": candidate["stock_name"],
                    "tier2_review_id": candidate["tier2_review_id"],
                    "industry_model": model_code,
                    "json_path": str(json_path),
                    "markdown_path": str(markdown_path),
                    "check_count": len(model.rules),
                }
            )
        index = {
            "run_id": run_id,
            "rules_version": self.registry.rules_version,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "template_count": len(exported),
            "templates": exported,
            "import_command": "python main.py import-tier3 --file FILLED_RESULTS.json",
        }
        index_path = root / "index.json"
        index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        index["index_path"] = str(index_path)
        return index

    @staticmethod
    def _validate_classification(value: Any) -> dict[str, Any]:
        required = {"symbol", "industry_model", "industry", "rationale", "sources"}
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError("行业分类字段不完整或包含未知字段")
        symbol = str(value["symbol"]).strip()
        if symbol.isdigit() and len(symbol) <= 6:
            symbol = symbol.zfill(6)
        if not re.fullmatch(r"\d{6}", symbol):
            raise ValueError(f"无效行业分类股票代码: {value['symbol']}")
        if not str(value["industry"]).strip() or len(str(value["rationale"]).strip()) < 5:
            raise ValueError(f"{symbol}行业名称或分类依据不足")
        sources = value["sources"]
        source_fields = {
            "title",
            "publisher",
            "date",
            "available_at",
            "url_or_document",
            "page_or_section",
            "snapshot_path",
            "content_sha256",
            "evidence_excerpt",
            "supported_claims",
        }
        optional_source_fields = {"extracted_text_path", "extracted_text_sha256"}
        if not isinstance(sources, list) or not sources:
            raise ValueError(f"{symbol}行业分类缺少来源")
        for source in sources:
            if (
                not isinstance(source, dict)
                or not source_fields.issubset(source)
                or set(source).difference(source_fields | optional_source_fields)
            ):
                raise ValueError(f"{symbol}行业分类来源字段不完整")
            try:
                date.fromisoformat(str(source["date"]))
            except ValueError as exc:
                raise ValueError(f"{symbol}行业分类来源日期无效") from exc
            if any(not str(source[field]).strip() for field in source_fields - {"date"}):
                raise ValueError(f"{symbol}行业分类来源存在空字段")
        return {**value, "symbol": symbol}

    @staticmethod
    def _absolute_source_paths(
        source: dict[str, Any], base_dir: Path
    ) -> dict[str, Any]:
        normalized = dict(source)
        for field in ("snapshot_path", "extracted_text_path"):
            value = normalized.get(field)
            if not value:
                continue
            path = Path(str(value)).expanduser()
            if not path.is_absolute():
                path = base_dir / path
            normalized[field] = str(path.resolve())
        return normalized

    @staticmethod
    def render_markdown(candidate, classification, model) -> str:
        lines = [
            f"# {candidate['symbol']} {candidate['stock_name']} Stage C风险研究",
            "",
            f"- as-of：{candidate['as_of_date']}",
            f"- Stage B review：`{candidate['tier2_review_id']}`",
            f"- 行业：{classification['industry']}",
            f"- 模型：{model.class_name} (`{model.model_code}`)",
            f"- 模型说明：{model.description}",
            "",
            "明确结论必须填入事实、反方证据和截至as-of可得的来源；缺证据保持UNKNOWN。",
            "",
            "| check_id | 类别 | 效果 | 检查定义 | 规则依据 |",
            "|---|---|---|---|---|",
        ]
        for rule in model.rules:
            lines.append(
                f"| {rule.rule_id} | {rule.category} | {rule.effect} | "
                f"{rule.description} | {rule.basis} |"
            )
        lines.append("")
        return "\n".join(lines)


def load_classifications(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("classifications"), list):
        payload = payload["classifications"]
    if not isinstance(payload, list) or not payload:
        raise ValueError("行业分类文件必须是非空数组或含classifications数组的对象")
    required = {"symbol", "industry_model", "industry", "rationale", "sources"}
    for index, item in enumerate(payload):
        if not isinstance(item, dict) or set(item) != required:
            raise ValueError(f"classifications[{index}]字段不完整或包含未知字段")
    return payload
