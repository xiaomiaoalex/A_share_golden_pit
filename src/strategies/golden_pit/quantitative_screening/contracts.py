"""Typed contracts for strict Tier1 screening.

The contracts deliberately separate business decisions from data acquisition
state.  A known hard failure remains a business ``FAIL`` even when later fields
were not fetched, while the independent data status records ``PARTIAL`` or
``ERROR``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Optional

from src.data.point_in_time.models import (
    CorporateAction,
    DividendEvent,
    FinancialReportFact,
    MarketSnapshot,
    RiskWarningStatus,
)

__all__ = [
    "BusinessStatus",
    "CorporateAction",
    "DataStatus",
    "DividendEvent",
    "FinancialReportFact",
    "MarketSnapshot",
    "QuarterlyMetric",
    "RiskWarningStatus",
    "Tier1Decision",
]


class BusinessStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    PENDING = "PENDING"
    NOT_COMPARABLE = "NOT_COMPARABLE"


class DataStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    ERROR = "ERROR"


@dataclass(frozen=True)
class QuarterlyMetric:
    symbol: str
    quarter: date
    revenue_single: Optional[float]
    parent_np_single: Optional[float]
    prior_year_revenue_single: Optional[float]
    prior_year_parent_np_single: Optional[float]
    revenue_yoy: Optional[float]
    parent_np_yoy: Optional[float]
    revenue_comparable: bool
    parent_np_comparable: bool
    formula: str
    missing_fields: tuple[str, ...] = ()
    source_observation_ids: tuple[int, ...] = ()


@dataclass
class Tier1Decision:
    symbol: str
    stock_name: str
    as_of_date: date
    price_date: Optional[date]
    business_status: BusinessStatus
    data_status: DataStatus
    screen_status: str
    selected_pe_ttm: Optional[float]
    supplier_pe_ttm: Optional[float]
    self_pe_ttm: Optional[float]
    pe_selection_method: Optional[str]
    dividend_yield_ttm: Optional[float]
    dividend_ttm_raw_per_share: Optional[float]
    dividend_ttm_adjusted_per_share: Optional[float]
    risk_warning: Optional[bool]
    trend_quarters: list[str]
    revenue_yoy_sequence: list[Optional[float]]
    parent_np_yoy_sequence: list[Optional[float]]
    failed_conditions: list[dict[str, Any]] = field(default_factory=list)
    pending_fields: list[str] = field(default_factory=list)
    error_fields: list[str] = field(default_factory=list)
    skipped_fields: list[str] = field(default_factory=list)
    not_comparable_reasons: list[str] = field(default_factory=list)
    quality_warnings: list[str] = field(default_factory=list)
    secondary_queues: list[str] = field(default_factory=list)
    calculation_version: str = "tier1-v2.1.0"
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["business_status"] = self.business_status.value
        result["data_status"] = self.data_status.value
        result["as_of_date"] = self.as_of_date.isoformat()
        result["price_date"] = self.price_date.isoformat() if self.price_date else None
        result["created_at"] = self.created_at.isoformat()
        return result
