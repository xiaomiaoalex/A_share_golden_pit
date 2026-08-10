"""Tier1 v2 strict screening configuration.

This module is intentionally separate from the legacy three-tier thresholds.
Changing these values creates a new calculation contract and therefore requires
an explicit ``calculation_version`` bump.
"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Tier1Config:
    """Business rules confirmed for Stage A."""

    max_pe_ttm: float = 15.0
    min_dividend_yield_ttm: float = 0.05
    trend_quarters: int = 2
    trend_rule: str = "POSITIVE_GROWTH"
    # Retained for exact continuation of pre-v2.2 run snapshots.
    strict_improvement: bool = False
    revenue_metric: str = "OPERATE_INCOME"
    profit_metric: str = "PARENT_NETPROFIT"
    dividend_tax_basis: str = "PRE_TAX"
    current_supplier_window_days: int = 7
    pe_mismatch_warning_ratio: float = 0.05
    calculation_version: str = "tier1-v2.2.0"

    def __post_init__(self) -> None:
        if self.trend_rule not in {"POSITIVE_GROWTH", "STRICT_IMPROVEMENT"}:
            raise ValueError(f"未知趋势规则: {self.trend_rule}")
        if self.trend_quarters < 2:
            raise ValueError("趋势判断至少需要两个连续季度")

    def to_dict(self) -> dict:
        return asdict(self)
