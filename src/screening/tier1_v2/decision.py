"""Fail-closed Tier1 decision state machine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from config.tier1 import Tier1Config

from .contracts import (
    BusinessStatus,
    DataStatus,
    QuarterlyMetric,
    Tier1Decision,
)
from .metrics import valid_number
from .quarterly import is_consecutive_window


@dataclass
class DecisionInput:
    symbol: str
    stock_name: str
    as_of_date: date
    price_date: Optional[date]
    selected_pe_ttm: Optional[float]
    supplier_pe_ttm: Optional[float]
    self_pe_ttm: Optional[float]
    pe_selection_method: Optional[str]
    dividend_yield_ttm: Optional[float]
    dividend_ttm_raw_per_share: Optional[float]
    dividend_ttm_adjusted_per_share: Optional[float]
    risk_warning: Optional[bool]
    quarterly_window: list[QuarterlyMetric]
    error_fields: list[str] = field(default_factory=list)
    skipped_fields: list[str] = field(default_factory=list)
    quality_warnings: list[str] = field(default_factory=list)


def _failure(condition: str, actual: object, operator: str, threshold: object) -> dict:
    return {
        "condition": condition,
        "actual": actual,
        "operator": operator,
        "threshold": threshold,
    }


def evaluate_tier1(
    data: DecisionInput, config: Tier1Config | None = None
) -> Tier1Decision:
    config = config or Tier1Config()
    failures: list[dict] = []
    pending: list[str] = []
    not_comparable: list[str] = []
    secondary_queues: list[str] = []

    pe = valid_number(data.selected_pe_ttm, positive=True)
    if pe is None:
        pending.append("pe_ttm")
    elif not pe < config.max_pe_ttm:
        failures.append(_failure("pe_ttm", pe, "<", config.max_pe_ttm))

    dividend_yield = valid_number(data.dividend_yield_ttm)
    if dividend_yield is None or dividend_yield < 0:
        pending.append("dividend_yield_ttm")
    elif not dividend_yield > config.min_dividend_yield_ttm:
        failures.append(
            _failure(
                "dividend_yield_ttm",
                dividend_yield,
                ">",
                config.min_dividend_yield_ttm,
            )
        )

    risk_warning = data.risk_warning if isinstance(data.risk_warning, bool) else None
    if risk_warning is None:
        pending.append("risk_warning_status")
    elif risk_warning:
        failures.append(_failure("risk_warning", True, "==", False))

    window = sorted(data.quarterly_window, key=lambda item: item.quarter)
    if len(window) != config.trend_quarters:
        pending.append("quarterly_trend_window")
    elif not is_consecutive_window(window):
        pending.append("consecutive_quarterly_trend_window")

    revenue_sequence = [valid_number(item.revenue_yoy) for item in window]
    parent_np_sequence = [valid_number(item.parent_np_yoy) for item in window]
    strict_trend = (
        config.strict_improvement or config.trend_rule == "STRICT_IMPROVEMENT"
    )

    if len(window) == config.trend_quarters and is_consecutive_window(window):
        prior_parent_np = [
            valid_number(item.prior_year_parent_np_single) for item in window
        ]
        prior_revenue = [
            valid_number(item.prior_year_revenue_single) for item in window
        ]
        if any(value is None for value in prior_parent_np):
            pending.append("prior_year_parent_np")
        elif any(value <= 0 for value in prior_parent_np):
            not_comparable.append("利润同比窗口存在上年同期归母净利润<=0")
            secondary_queues.append("TURNAROUND_WATCHLIST")
        elif any(value is None for value in parent_np_sequence):
            pending.append("parent_np_yoy_sequence")
        elif strict_trend and not all(
            current > previous
            for previous, current in zip(parent_np_sequence, parent_np_sequence[1:])
        ):
            failures.append(
                _failure(
                    "parent_np_yoy_strictly_improving",
                    parent_np_sequence,
                    "each_next > previous",
                    True,
                )
            )
        elif not strict_trend and not all(
            value > 0 for value in parent_np_sequence
        ):
            failures.append(
                _failure(
                    "parent_np_yoy_consecutive_positive",
                    parent_np_sequence,
                    "each >",
                    0,
                )
            )

        if any(value is None for value in prior_revenue):
            pending.append("prior_year_operating_revenue")
        elif any(value <= 0 for value in prior_revenue):
            not_comparable.append("收入同比窗口存在上年同期营业收入<=0")
        elif any(value is None for value in revenue_sequence):
            pending.append("revenue_yoy_sequence")
        elif strict_trend and not all(
            current > previous
            for previous, current in zip(revenue_sequence, revenue_sequence[1:])
        ):
            failures.append(
                _failure(
                    "revenue_yoy_strictly_improving",
                    revenue_sequence,
                    "each_next > previous",
                    True,
                )
            )
        elif not strict_trend and not all(
            value > 0 for value in revenue_sequence
        ):
            failures.append(
                _failure(
                    "revenue_yoy_consecutive_positive",
                    revenue_sequence,
                    "each >",
                    0,
                )
            )

    pending = list(dict.fromkeys(pending))
    errors = list(dict.fromkeys(data.error_fields))
    skipped = list(dict.fromkeys(data.skipped_fields))

    if errors:
        data_status = DataStatus.ERROR
    elif pending or skipped:
        data_status = DataStatus.PARTIAL
    else:
        data_status = DataStatus.COMPLETE

    if failures:
        business_status = BusinessStatus.FAIL
        screen_status = "FAIL"
    elif not_comparable:
        business_status = BusinessStatus.NOT_COMPARABLE
        screen_status = "TURNAROUND_WATCHLIST" if "TURNAROUND_WATCHLIST" in secondary_queues else "NOT_COMPARABLE"
    elif errors:
        business_status = BusinessStatus.PENDING
        screen_status = "DATA_ERROR"
    elif pending or skipped:
        business_status = BusinessStatus.PENDING
        screen_status = "PENDING_DATA"
    else:
        business_status = BusinessStatus.PASS
        screen_status = "PASS"

    return Tier1Decision(
        symbol=data.symbol,
        stock_name=data.stock_name,
        as_of_date=data.as_of_date,
        price_date=data.price_date,
        business_status=business_status,
        data_status=data_status,
        screen_status=screen_status,
        selected_pe_ttm=pe,
        supplier_pe_ttm=valid_number(data.supplier_pe_ttm, positive=True),
        self_pe_ttm=valid_number(data.self_pe_ttm, positive=True),
        pe_selection_method=data.pe_selection_method,
        dividend_yield_ttm=dividend_yield,
        dividend_ttm_raw_per_share=valid_number(data.dividend_ttm_raw_per_share),
        dividend_ttm_adjusted_per_share=valid_number(data.dividend_ttm_adjusted_per_share),
        risk_warning=risk_warning,
        trend_quarters=[item.quarter.isoformat() for item in window],
        revenue_yoy_sequence=revenue_sequence,
        parent_np_yoy_sequence=parent_np_sequence,
        failed_conditions=failures,
        pending_fields=pending,
        error_fields=errors,
        skipped_fields=skipped,
        not_comparable_reasons=not_comparable,
        quality_warnings=list(dict.fromkeys(data.quality_warnings)),
        secondary_queues=list(dict.fromkeys(secondary_queues)),
        calculation_version=config.calculation_version,
    )
