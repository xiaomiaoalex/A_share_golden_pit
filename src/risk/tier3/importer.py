"""Validate, bind and atomically import Stage C risk research inputs."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from src.evidence import verify_sources
from src.storage.tier3_repository import Tier3Repository

from .engine import RiskAssessmentEngine
from .models import RiskModelRegistry


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


class Tier3RiskImporter:
    def __init__(
        self,
        repository: Tier3Repository,
        registry: RiskModelRegistry,
        schema_path: str | Path,
    ):
        self.repository = repository
        self.registry = registry
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(schema, format_checker=FormatChecker())
        self.engine = RiskAssessmentEngine()

    def import_file(self, path: str | Path) -> dict[str, Any]:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(payload, list):
            inputs = payload
        elif isinstance(payload, dict) and isinstance(payload.get("results"), list):
            inputs = payload["results"]
        elif isinstance(payload, dict):
            inputs = [payload]
        else:
            raise TypeError("Tier3输入必须是对象、对象数组或含results数组的对象")
        if not inputs:
            raise ValueError("Tier3输入文件为空")
        records = [
            self._validate_and_prepare(item, index, Path(path).resolve().parent)
            for index, item in enumerate(inputs)
        ]
        ids = self.repository.save_batch(records)
        return {
            "imported_count": len(ids),
            "risk_assessment_ids": ids,
            "system_statuses": {
                record["symbol"]: record["assessment"]["system_status"]
                for record in records
            },
        }

    def _validate_and_prepare(
        self, risk_input: Any, index: int, source_base_dir: Path
    ) -> dict[str, Any]:
        if not isinstance(risk_input, dict):
            raise TypeError(f"results[{index}]不是JSON对象")
        errors = sorted(self.validator.iter_errors(risk_input), key=lambda err: list(err.path))
        if errors:
            detail = "; ".join(
                f"{'.'.join(str(part) for part in error.path) or '$'}: {error.message}"
                for error in errors[:10]
            )
            raise ValueError(f"Tier3输入未通过JSON Schema（results[{index}]）: {detail}")

        as_of = date.fromisoformat(risk_input["as_of_date"])
        verify_sources(
            risk_input["industry_classification"]["sources"],
            as_of=as_of,
            base_dir=source_base_dir,
            required_claims=[risk_input["industry_classification"]["rationale"]],
            context=f"results[{index}].industry",
        )
        model_code = risk_input["industry_classification"]["industry_model"]
        model = self.registry.get(model_code)
        check_ids = [item["check_id"] for item in risk_input["checks"]]
        expected = set(model.rule_map)
        if len(check_ids) != len(set(check_ids)) or set(check_ids) != expected:
            missing = sorted(expected - set(check_ids))
            extra = sorted(set(check_ids) - expected)
            raise ValueError(
                f"results[{index}]风险检查集合与{model_code}模型不一致; "
                f"missing={missing}, extra={extra}"
            )
        for item in risk_input["checks"]:
            rule = model.rule_map[item["check_id"]]
            status = item["status"]
            if status in {"TRIGGERED", "CLEAR"}:
                if not item["facts"] or not item["sources"]:
                    raise ValueError(
                        f"results[{index}].{rule.rule_id}形成明确结论时必须有事实和来源"
                    )
                if not item["counter_evidence"]:
                    raise ValueError(
                        f"results[{index}].{rule.rule_id}缺少反方证据审查"
                    )
            if status == "UNKNOWN" and item["confidence"] > 0.5:
                raise ValueError(
                    f"results[{index}].{rule.rule_id}证据未知却给出过高置信度"
                )
            if status == "NOT_APPLICABLE" and not rule.allow_not_applicable:
                raise ValueError(
                    f"results[{index}].{rule.rule_id}是该行业模型必要检查，不能标记不适用"
                )
            verify_sources(
                item["sources"],
                as_of=as_of,
                base_dir=source_base_dir,
                required_claims=item["facts"],
                context=f"results[{index}].{rule.rule_id}",
            )
            for metric in item["metrics"]:
                value = metric["value"]
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError(
                        f"results[{index}].{rule.rule_id}包含NaN或无穷指标"
                    )

        tier2 = self.repository.latest_tier2_pass(
            risk_input["run_id"], risk_input["symbol"]
        )
        bindings = {
            "as_of_date": tier2["as_of_date"],
            "tier2_review_id": tier2["tier2_review_id"],
        }
        for field, expected_value in bindings.items():
            if str(risk_input[field]) != str(expected_value):
                raise ValueError(
                    f"results[{index}].{field}与最新Stage B人工PASS不一致"
                )
        assessment = self.engine.evaluate(risk_input, model)
        return {
            "run_id": risk_input["run_id"],
            "symbol": risk_input["symbol"],
            "as_of_date": risk_input["as_of_date"],
            "tier2_review_id": risk_input["tier2_review_id"],
            "content_hash": _canonical_hash(risk_input),
            "risk_input": risk_input,
            "assessment": assessment,
        }
