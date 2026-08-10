"""Point-in-time quarterly financial reconstruction."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from typing import Iterable, Optional

from .contracts import FinancialReportFact, QuarterlyMetric


_QUARTER_ENDS = {
    1: (3, 31),
    2: (6, 30),
    3: (9, 30),
    4: (12, 31),
}


def _valid_number(value: object) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def quarter_number(period: date) -> int:
    for quarter, (month, day) in _QUARTER_ENDS.items():
        if period.month == month and period.day == day:
            return quarter
    raise ValueError(f"非标准季度报告期: {period.isoformat()}")


def quarter_end(year: int, quarter: int) -> date:
    month, day = _QUARTER_ENDS[quarter]
    return date(year, month, day)


def previous_quarter(period: date) -> date:
    quarter = quarter_number(period)
    if quarter == 1:
        return quarter_end(period.year - 1, 4)
    return quarter_end(period.year, quarter - 1)


def same_quarter_previous_year(period: date) -> date:
    return quarter_end(period.year - 1, quarter_number(period))


def quarter_ordinal(period: date) -> int:
    return period.year * 4 + quarter_number(period) - 1


def _latest_available_facts(
    facts: Iterable[FinancialReportFact], as_of_date: date
) -> dict[date, FinancialReportFact]:
    grouped: dict[date, list[FinancialReportFact]] = defaultdict(list)
    for fact in facts:
        available_date = fact.announcement_date
        if fact.revision_at is not None:
            available_date = max(available_date, fact.revision_at.date())
        if available_date <= as_of_date:
            grouped[fact.report_period].append(fact)

    selected: dict[date, FinancialReportFact] = {}
    for period, revisions in grouped.items():
        selected[period] = max(
            revisions,
            key=lambda item: (
                item.revision_at.isoformat() if item.revision_at else "",
                item.announcement_date.isoformat(),
                item.source,
            ),
        )
    return selected


def _single_quarter_value(
    period: date,
    facts: dict[date, FinancialReportFact],
    field_name: str,
) -> tuple[Optional[float], list[int], list[str]]:
    current = facts.get(period)
    if current is None:
        return None, [], [f"{field_name}:{period.isoformat()}"]

    current_value = _valid_number(getattr(current, field_name))
    ids = [current.source_observation_id] if current.source_observation_id else []
    if current_value is None:
        return None, ids, [f"{field_name}:{period.isoformat()}"]

    quarter = quarter_number(period)
    if quarter == 1:
        return current_value, ids, []

    predecessor_period = quarter_end(period.year, quarter - 1)
    predecessor = facts.get(predecessor_period)
    if predecessor is None:
        return None, ids, [f"{field_name}:{predecessor_period.isoformat()}"]
    predecessor_value = _valid_number(getattr(predecessor, field_name))
    if predecessor.source_observation_id:
        ids.append(predecessor.source_observation_id)
    if predecessor_value is None:
        return None, ids, [f"{field_name}:{predecessor_period.isoformat()}"]
    return current_value - predecessor_value, ids, []


def build_quarterly_series(
    facts: Iterable[FinancialReportFact], as_of_date: date
) -> list[QuarterlyMetric]:
    """Convert cumulative reports into single-quarter point-in-time metrics."""

    selected = _latest_available_facts(facts, as_of_date)
    output: list[QuarterlyMetric] = []

    for period in sorted(selected):
        revenue, revenue_ids, revenue_missing = _single_quarter_value(
            period, selected, "operating_revenue"
        )
        parent_np, np_ids, np_missing = _single_quarter_value(
            period, selected, "parent_net_profit"
        )
        prior_period = same_quarter_previous_year(period)
        prior_revenue, prior_revenue_ids, prior_revenue_missing = _single_quarter_value(
            prior_period, selected, "operating_revenue"
        )
        prior_np, prior_np_ids, prior_np_missing = _single_quarter_value(
            prior_period, selected, "parent_net_profit"
        )

        revenue_comparable = prior_revenue is not None and prior_revenue > 0
        parent_np_comparable = prior_np is not None and prior_np > 0
        revenue_yoy = (
            revenue / prior_revenue - 1
            if revenue is not None and revenue_comparable
            else None
        )
        parent_np_yoy = (
            parent_np / prior_np - 1
            if parent_np is not None and parent_np_comparable
            else None
        )

        missing = tuple(
            dict.fromkeys(
                revenue_missing + np_missing + prior_revenue_missing + prior_np_missing
            )
        )
        source_ids = tuple(
            dict.fromkeys(
                revenue_ids + np_ids + prior_revenue_ids + prior_np_ids
            )
        )
        formula = (
            "Q1=Q1累计; Q2=H1累计-Q1累计; "
            "Q3=Q3累计-H1累计; Q4=年报累计-Q3累计; "
            "同比=本期单季度/上年同期单季度-1"
        )
        output.append(
            QuarterlyMetric(
                symbol=selected[period].symbol,
                quarter=period,
                revenue_single=revenue,
                parent_np_single=parent_np,
                prior_year_revenue_single=prior_revenue,
                prior_year_parent_np_single=prior_np,
                revenue_yoy=revenue_yoy,
                parent_np_yoy=parent_np_yoy,
                revenue_comparable=revenue_comparable,
                parent_np_comparable=parent_np_comparable,
                formula=formula,
                missing_fields=missing,
                source_observation_ids=source_ids,
            )
        )
    return output


def recent_quarter_window(
    series: Iterable[QuarterlyMetric], count: int = 3
) -> list[QuarterlyMetric]:
    """Return the latest disclosed quarters without skipping bad bases or gaps."""

    ordered = sorted(series, key=lambda item: item.quarter)
    return ordered[-count:] if len(ordered) >= count else ordered


def is_consecutive_window(window: Iterable[QuarterlyMetric]) -> bool:
    items = list(window)
    return all(
        quarter_ordinal(current.quarter) - quarter_ordinal(previous.quarter) == 1
        for previous, current in zip(items, items[1:])
    )


def ttm_parent_net_profit(
    series: Iterable[QuarterlyMetric], count: int = 4
) -> Optional[float]:
    ordered = sorted(series, key=lambda item: item.quarter)
    if len(ordered) < count:
        return None
    window = ordered[-count:]
    if not is_consecutive_window(window):
        return None
    values = [_valid_number(item.parent_np_single) for item in window]
    if any(value is None for value in values):
        return None
    total = sum(value for value in values if value is not None)
    return total if total > 0 else None
