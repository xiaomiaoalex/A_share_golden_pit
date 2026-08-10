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
    trend_quarters: int = 3
    strict_improvement: bool = True
    revenue_metric: str = "OPERATE_INCOME"
    profit_metric: str = "PARENT_NETPROFIT"
    dividend_tax_basis: str = "PRE_TAX"
    current_supplier_window_days: int = 7
    pe_mismatch_warning_ratio: float = 0.05
    calculation_version: str = "tier1-v2.1.0"

    def to_dict(self) -> dict:
        return asdict(self)
