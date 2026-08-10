"""Pure Tier1 valuation and dividend calculations."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional

from .contracts import CorporateAction, DividendEvent


def valid_number(value: object, *, positive: bool = False) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if positive and number <= 0:
        return None
    return number


def compute_self_pe_ttm(
    market_cap: object, ttm_parent_net_profit: object
) -> Optional[float]:
    cap = valid_number(market_cap, positive=True)
    profit = valid_number(ttm_parent_net_profit, positive=True)
    if cap is None or profit is None:
        return None
    return cap / profit


@dataclass(frozen=True)
class PESelection:
    selected: Optional[float]
    method: Optional[str]
    supplier: Optional[float]
    self_computed: Optional[float]
    warnings: tuple[str, ...] = ()


def select_pe_ttm(
    *,
    supplier_pe_ttm: object,
    self_pe_ttm: object,
    historical: bool,
    mismatch_warning_ratio: float = 0.05,
) -> PESelection:
    supplier = valid_number(supplier_pe_ttm, positive=True)
    self_value = valid_number(self_pe_ttm, positive=True)
    warnings: list[str] = []
    if supplier is not None and self_value is not None:
        difference = abs(supplier - self_value) / self_value
        if difference > mismatch_warning_ratio:
            warnings.append(
                f"供应商PE与点时自计算PE偏差{difference:.2%}，已同时保留"
            )
    if historical:
        return PESelection(
            selected=self_value,
            method="POINT_IN_TIME_SELF_COMPUTED" if self_value is not None else None,
            supplier=supplier,
            self_computed=self_value,
            warnings=tuple(warnings),
        )
    selected = supplier if supplier is not None else self_value
    method = None
    if supplier is not None:
        method = "VALIDATED_SUPPLIER"
    elif self_value is not None:
        method = "CURRENT_SELF_COMPUTED_FALLBACK"
    return PESelection(
        selected=selected,
        method=method,
        supplier=supplier,
        self_computed=self_value,
        warnings=tuple(warnings),
    )


def one_calendar_year_before(value: date) -> date:
    try:
        return value.replace(year=value.year - 1)
    except ValueError:
        return value.replace(year=value.year - 1, day=28)


@dataclass(frozen=True)
class AdjustedDividendEvent:
    ex_date: date
    raw_per_share: float
    adjusted_per_share: float
    adjustment_factor: float
    provider_adjusted: bool


@dataclass(frozen=True)
class DividendCalculation:
    raw_per_share: Optional[float]
    adjusted_per_share: Optional[float]
    dividend_yield_ttm: Optional[float]
    events: tuple[AdjustedDividendEvent, ...]


def calculate_dividend_ttm(
    *,
    events: Iterable[DividendEvent],
    actions: Iterable[CorporateAction],
    as_of_date: date,
    close_price: object,
) -> DividendCalculation:
    """Calculate pre-tax TTM dividend yield on the as-of share basis.

    The window is ``(as_of_date - 1 calendar year, as_of_date]``.  Raw cash per
    share is always preserved.  Corporate actions are applied only when the
    provider has not already adjusted the event.
    """

    price = valid_number(close_price, positive=True)
    window_start = one_calendar_year_before(as_of_date)
    valid_actions = [
        action
        for action in actions
        if action.effective_date <= as_of_date
        and valid_number(action.share_factor, positive=True) is not None
    ]
    adjusted_events: list[AdjustedDividendEvent] = []

    for event in events:
        cash = valid_number(event.raw_cash_per_share_pre_tax)
        if cash is None or cash < 0:
            continue
        if event.announcement_date is not None and event.announcement_date > as_of_date:
            continue
        normalized_status = str(event.status).strip().upper()
        if not any(
            marker in normalized_status
            for marker in ("实施", "IMPLEMENTED", "COMPLETED")
        ):
            continue
        if not (window_start < event.ex_date <= as_of_date):
            continue
        factor = 1.0
        if not event.provider_adjusted:
            for action in valid_actions:
                if event.ex_date <= action.effective_date <= as_of_date:
                    if not action.provider_adjusted:
                        factor *= action.share_factor
        adjusted = cash if event.provider_adjusted else cash / factor
        adjusted_events.append(
            AdjustedDividendEvent(
                ex_date=event.ex_date,
                raw_per_share=cash,
                adjusted_per_share=adjusted,
                adjustment_factor=factor,
                provider_adjusted=event.provider_adjusted,
            )
        )

    raw_total = sum(item.raw_per_share for item in adjusted_events)
    adjusted_total = sum(item.adjusted_per_share for item in adjusted_events)
    if price is None:
        dividend_yield = None
    else:
        dividend_yield = adjusted_total / price
    return DividendCalculation(
        raw_per_share=raw_total if adjusted_events else 0.0,
        adjusted_per_share=adjusted_total if adjusted_events else 0.0,
        dividend_yield_ttm=dividend_yield,
        events=tuple(adjusted_events),
    )
