"""Validate evidence-bound AI output and derive a fail-closed Tier2 recommendation."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from src.evidence import verify_sources
from src.strategies.golden_pit.persistence.tier2_repository import Tier2Repository

from .constants import CRITICAL_DIMENSIONS, DIMENSIONS, SCENARIOS, SCHEMA_VERSION


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def derive_system_recommendation(assessment: dict[str, Any]) -> str:
    """Apply vetoes before any ranking or human confirmation."""

    verdicts = {item["dimension"]: item["verdict"] for item in assessment["dimensions"]}
    if any(verdict == "FAIL" for verdict in verdicts.values()):
        derived = "REJECT"
    elif any(
        verdicts.get(dimension) in {"WARN", "INSUFFICIENT_EVIDENCE"}
        for dimension in CRITICAL_DIMENSIONS
    ):
        derived = "REVIEW"
    else:
        derived = "PASS"
        scenarios = {
            item["scenario"]: item for item in assessment["scenario_analysis"]
        }
        for name in SCENARIOS:
            scenario = scenarios[name]
            if (
                scenario["value_per_share"] is None
                or scenario["annualized_return_3y"] is None
                or scenario["annualized_return_5y"] is None
            ):
                derived = "REVIEW"
                break
        if scenarios["PESSIMISTIC"]["permanent_loss_risk"] == "UNKNOWN":
            derived = "REVIEW"

    # A contradictory top-level AI recommendation may only make the result more
    # conservative; it can never cancel a dimension veto or evidence gap.
    rank = {"REJECT": 0, "REVIEW": 1, "PASS": 2}
    ai_recommendation = assessment["recommendation"]
    return min((derived, ai_recommendation), key=rank.__getitem__)


class Tier2AssessmentImporter:
    def __init__(self, repository: Tier2Repository, schema_path: str | Path):
        self.repository = repository
        self.schema_path = Path(schema_path)
        schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(schema, format_checker=FormatChecker())

    def import_file(self, path: str | Path) -> dict[str, Any]:
        source = Path(path)
        payload = json.loads(source.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            assessments = payload
        elif isinstance(payload, dict) and isinstance(payload.get("results"), list):
            assessments = payload["results"]
        elif isinstance(payload, dict):
            assessments = [payload]
        else:
            raise TypeError("AI结果必须是单个对象、对象数组或含results数组的对象")
        if not assessments:
            raise ValueError("AI结果文件为空")

        # Validate every item before opening the write transaction: one bad item
        # cannot leave a partially imported batch.
        records = [
            self._validate_and_prepare(item, index, source.parent)
            for index, item in enumerate(assessments)
        ]
        assessment_ids = self.repository.save_assessments_atomic(records)
        return {
            "imported_count": len(assessment_ids),
            "assessment_ids": assessment_ids,
            "system_recommendations": {
                record["symbol"]: record["system_recommendation"] for record in records
            },
        }

    def _validate_and_prepare(
        self, assessment: Any, index: int, source_base_dir: Path
    ) -> dict[str, Any]:
        if not isinstance(assessment, dict):
            raise TypeError(f"results[{index}]不是JSON对象")
        errors = sorted(self.validator.iter_errors(assessment), key=lambda err: list(err.path))
        if errors:
            details = "; ".join(
                f"{'.'.join(str(item) for item in error.path) or '$'}: {error.message}"
                for error in errors[:10]
            )
            raise ValueError(f"AI结果未通过JSON Schema（results[{index}]）: {details}")

        dimensions = [item["dimension"] for item in assessment["dimensions"]]
        if len(set(dimensions)) != len(dimensions) or set(dimensions) != set(DIMENSIONS):
            raise ValueError(f"results[{index}]必须包含七个不重复的规定维度")
        scenarios = [item["scenario"] for item in assessment["scenario_analysis"]]
        if len(set(scenarios)) != len(scenarios) or set(scenarios) != set(SCENARIOS):
            raise ValueError(f"results[{index}]必须包含三个不重复的规定情景")
        for dimension in assessment["dimensions"]:
            if dimension["verdict"] != "INSUFFICIENT_EVIDENCE":
                if not dimension["facts"] or not dimension["sources"]:
                    raise ValueError(
                        f"results[{index}].{dimension['dimension']}形成结论时必须有事实和来源"
                    )
                if not dimension["counter_evidence"]:
                    raise ValueError(
                        f"results[{index}].{dimension['dimension']}缺少反方证据审查"
                    )
            if dimension["facts"] and not dimension["sources"]:
                raise ValueError(
                    f"results[{index}].{dimension['dimension']}事实缺少可追溯来源"
                )
            verify_sources(
                dimension["sources"],
                as_of=date.fromisoformat(assessment["as_of_date"]),
                base_dir=source_base_dir,
                required_claims=dimension["facts"],
                context=f"results[{index}].{dimension['dimension']}",
            )

        package = self.repository.package(assessment["evidence_package_id"])
        if package is None:
            raise ValueError(f"results[{index}]引用了未知证据包")
        latest_package = self.repository.latest_package(
            str(package["run_id"]), str(package["symbol"])
        )
        if (
            latest_package is None
            or latest_package["package_id"] != package["package_id"]
        ):
            raise ValueError(f"results[{index}]引用的证据包已被更新版本替代")
        bindings = {
            "run_id": package["run_id"],
            "symbol": package["symbol"],
            "as_of_date": package["as_of_date"],
            "evidence_content_hash": package["content_hash"],
        }
        for field, expected in bindings.items():
            if str(assessment[field]) != str(expected):
                raise ValueError(
                    f"results[{index}].{field}与证据包不一致，拒绝导入陈旧或串股结论"
                )
        if assessment["schema_version"] != SCHEMA_VERSION:
            raise ValueError(f"results[{index}]使用了不支持的Schema版本")

        system_recommendation = derive_system_recommendation(assessment)
        return {
            "package_id": package["package_id"],
            "run_id": package["run_id"],
            "symbol": package["symbol"],
            "as_of_date": package["as_of_date"],
            "schema_version": assessment["schema_version"],
            "ai_provider": assessment["ai_provider"],
            "ai_model": assessment.get("ai_model"),
            "ai_recommendation": assessment["recommendation"],
            "system_recommendation": system_recommendation,
            "content_hash": _canonical_hash(assessment),
            "assessment": assessment,
        }
