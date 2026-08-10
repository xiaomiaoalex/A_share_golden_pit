"""Stable business vocabulary for Tier2 v1."""

PACKAGE_VERSION = "tier2-evidence-v1.0"
SCHEMA_VERSION = "tier2-ai-v1.0"

DIMENSIONS = (
    "demand_durability",
    "competitive_position",
    "dividend_sustainability",
    "earnings_quality",
    "market_mispricing",
    "risk_reward_asymmetry",
    "long_cycle_fit",
)

CRITICAL_DIMENSIONS = frozenset(DIMENSIONS)
SCENARIOS = ("PESSIMISTIC", "BASE", "OPTIMISTIC")

EVIDENCE_SECTIONS = (
    "tier1_decision",
    "financial_history_5y",
    "recent_quarterly_financials",
    "profitability_and_capital_returns",
    "cash_flow_and_capex",
    "dividend_sustainability",
    "balance_sheet_and_working_capital",
    "non_recurring_items",
    "segment_and_region",
    "industry_demand_and_competition",
    "market_share_capacity_and_capex",
    "historical_valuation",
    "reverse_valuation",
    "source_lineage",
)
