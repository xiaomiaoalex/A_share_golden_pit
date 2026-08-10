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
class MarketSnapshot:
    symbol: str
    price_date: date
    close_price: Optional[float]
    market_cap: Optional[float]
    total_shares: Optional[float]
    supplier_pe_ttm: Optional[float]
    source: str
    source_observation_id: Optional[int] = None


@dataclass(frozen=True)
class FinancialReportFact:
    symbol: str
    report_period: date
    announcement_date: date
    operating_revenue: Optional[float]
    parent_net_profit: Optional[float]
    source: str
    revision_at: Optional[datetime] = None
    source_observation_id: Optional[int] = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DividendEvent:
    symbol: str
    ex_date: date
    raw_cash_per_share_pre_tax: float
    status: str
    source: str
    provider_adjusted: bool = False
    announcement_date: Optional[date] = None
    report_period: Optional[date] = None
    source_observation_id: Optional[int] = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CorporateAction:
    symbol: str
    effective_date: date
    share_factor: float
    source: str
    provider_adjusted: bool = False
    source_observation_id: Optional[int] = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskWarningStatus:
    symbol: str
    as_of_date: date
    is_risk_warning: Optional[bool]
    security_name: Optional[str]
    source: str
    effective_date: Optional[date] = None
    source_observation_id: Optional[int] = None
    reason: Optional[str] = None


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
    calculation_version: str = "tier1-v2.0.0"
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["business_status"] = self.business_status.value
        result["data_status"] = self.data_status.value
        result["as_of_date"] = self.as_of_date.isoformat()
        result["price_date"] = self.price_date.isoformat() if self.price_date else None
        result["created_at"] = self.created_at.isoformat()
        return result
