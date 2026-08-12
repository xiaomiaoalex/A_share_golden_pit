"""Config-driven industry adapters for Stage C.

The adapters deliberately expose evidence rules instead of pretending that a
single debt/FCF threshold works for industrials, banks, insurers and property
developers alike.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VALID_CATEGORIES = {
    "ACCOUNTING_QUALITY",
    "LIQUIDITY",
    "DIVIDEND_SUSTAINABILITY",
    "GOVERNANCE",
    "CYCLE_PEAK",
    "STRUCTURAL_VALUE_TRAP",
}


@dataclass(frozen=True)
class RiskRule:
    rule_id: str
    category: str
    effect: str
    description: str
    basis: str
    allow_not_applicable: bool = False

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RiskRule:
        rule = cls(
            rule_id=str(value["id"]),
            category=str(value["category"]),
            effect=str(value["effect"]),
            description=str(value["description"]),
            basis=str(value["basis"]),
            allow_not_applicable=bool(value.get("allow_not_applicable", False)),
        )
        if not re.fullmatch(r"[a-z0-9_]+", rule.rule_id):
            raise ValueError(f"非法风险规则ID: {rule.rule_id}")
        if rule.category not in VALID_CATEGORIES:
            raise ValueError(f"{rule.rule_id}使用了非法风险类别")
        if rule.effect not in {"HARD_VETO", "WARNING"}:
            raise ValueError(f"{rule.rule_id}使用了非法规则效果")
        if not rule.description.strip() or not rule.basis.strip():
            raise ValueError(f"{rule.rule_id}缺少规则定义或依据")
        return rule

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.rule_id,
            "category": self.category,
            "effect": self.effect,
            "description": self.description,
            "basis": self.basis,
            "allow_not_applicable": self.allow_not_applicable,
        }


class BaseRiskModel:
    model_code = ""
    class_name = "BaseRiskModel"

    def __init__(self, rules_version: str, description: str, rules: list[RiskRule]):
        self.rules_version = rules_version
        self.description = description
        self._rules = tuple(rules)

    @property
    def rules(self) -> tuple[RiskRule, ...]:
        return self._rules

    @property
    def rule_map(self) -> dict[str, RiskRule]:
        return {rule.rule_id: rule for rule in self.rules}


class IndustrialRiskModel(BaseRiskModel):
    model_code = "INDUSTRIAL"
    class_name = "IndustrialRiskModel"


class BankRiskModel(BaseRiskModel):
    model_code = "BANK"
    class_name = "BankRiskModel"


class InsuranceRiskModel(BaseRiskModel):
    model_code = "INSURANCE"
    class_name = "InsuranceRiskModel"


class RealEstateRiskModel(BaseRiskModel):
    model_code = "REAL_ESTATE"
    class_name = "RealEstateRiskModel"


MODEL_CLASSES = {
    "INDUSTRIAL": IndustrialRiskModel,
    "BANK": BankRiskModel,
    "INSURANCE": InsuranceRiskModel,
    "REAL_ESTATE": RealEstateRiskModel,
}


class RiskModelRegistry:
    def __init__(self, config_path: str | Path):
        path = Path(config_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.rules_version = str(payload["rules_version"])
        self.evidence_policy = str(payload["evidence_policy"])
        common = [RiskRule.from_dict(item) for item in payload["common_rules"]]
        self._models: dict[str, BaseRiskModel] = {}
        for code, model_config in payload["models"].items():
            if code not in MODEL_CLASSES:
                raise ValueError(f"未知行业模型配置: {code}")
            configured_class = str(model_config["class"])
            model_class = MODEL_CLASSES[code]
            if configured_class != model_class.class_name:
                raise ValueError(f"{code}模型类配置不一致")
            additional = [
                RiskRule.from_dict(item) for item in model_config["additional_rules"]
            ]
            rules = [*common, *additional]
            ids = [rule.rule_id for rule in rules]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{code}存在重复风险规则")
            self._models[code] = model_class(
                self.rules_version, str(model_config["description"]), rules
            )

    def get(self, model_code: str) -> BaseRiskModel:
        try:
            return self._models[model_code]
        except KeyError as exc:
            raise ValueError(f"不支持的行业模型: {model_code}") from exc

    @property
    def model_codes(self) -> tuple[str, ...]:
        return tuple(self._models)
