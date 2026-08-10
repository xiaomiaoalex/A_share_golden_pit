"""Canonical paths for versioned Golden Pit research resources."""

from pathlib import Path

RESOURCE_ROOT = Path(__file__).resolve().parent / "resources"
EVIDENCE_SCHEMA = RESOURCE_ROOT / "tier2_ai_schema.json"
EVIDENCE_PROMPT = RESOURCE_ROOT / "tier2_ai_prompt_template.md"
RISK_INPUT_SCHEMA = RESOURCE_ROOT / "tier3_risk_input_schema.json"
RISK_RULES = RESOURCE_ROOT / "tier3_risk_rules.json"

__all__ = [
    "EVIDENCE_PROMPT",
    "EVIDENCE_SCHEMA",
    "RESOURCE_ROOT",
    "RISK_INPUT_SCHEMA",
    "RISK_RULES",
]
