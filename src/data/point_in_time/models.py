"""Strategy-neutral point-in-time market and financial data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional


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
