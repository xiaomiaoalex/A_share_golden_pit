"""Fail-closed Stage C risk decision engine."""

from __future__ import annotations

from typing import Any

from .models import BaseRiskModel


class RiskAssessmentEngine:
    assessment_version = "tier3-assessment-v1.0"

    def evaluate(
        self, risk_input: dict[str, Any], model: BaseRiskModel
    ) -> dict[str, Any]:
        checks = {item["check_id"]: item for item in risk_input["checks"]}
        hard_vetoes = []
        warnings = []
        value_traps = []
        supporting_evidence = []
        counter_evidence = []
        unknown_checks = []

        normalized_checks = []
        for rule in model.rules:
            item = checks[rule.rule_id]
            status = item["status"]
            normalized = {
                **item,
                "category": rule.category,
                "rule_effect": rule.effect,
                "rule_description": rule.description,
                "rule_basis": rule.basis,
            }
            normalized_checks.append(normalized)
            if status == "UNKNOWN":
                unknown_checks.append(rule.rule_id)
                continue
            if status == "NOT_APPLICABLE":
                continue
            if status == "CLEAR":
                supporting_evidence.extend(
                    {"check_id": rule.rule_id, "fact": fact}
                    for fact in item["facts"]
                )
                continue
            signal = {
                "check_id": rule.rule_id,
                "category": rule.category,
                "description": rule.description,
                "reasoning_summary": item["reasoning_summary"],
                "facts": item["facts"],
                "sources": item["sources"],
            }
            counter_evidence.append(signal)
            if rule.effect == "HARD_VETO":
                hard_vetoes.append(signal)
            else:
                warnings.append(signal)
            if rule.category in {"CYCLE_PEAK", "STRUCTURAL_VALUE_TRAP"}:
                value_traps.append(signal)

        if hard_vetoes:
            status = "REJECT"
        elif unknown_checks or warnings:
            status = "REVIEW"
        else:
            status = "PASS"

        return {
            "run_id": risk_input["run_id"],
            "symbol": risk_input["symbol"],
            "as_of_date": risk_input["as_of_date"],
            "tier2_review_id": risk_input["tier2_review_id"],
            "industry_model": model.model_code,
            "industry_model_class": model.class_name,
            "rules_version": model.rules_version,
            "assessment_version": self.assessment_version,
            "system_status": status,
            "data_status": "PARTIAL" if unknown_checks else "COMPLETE",
            "hard_vetoes": hard_vetoes,
            "risk_warnings": warnings,
            "value_trap_signals": value_traps,
            "supporting_evidence": supporting_evidence,
            "counter_evidence": counter_evidence,
            "unknown_checks": unknown_checks,
            "falsification_conditions": risk_input["falsification_conditions"],
            "normalized_checks": normalized_checks,
        }
