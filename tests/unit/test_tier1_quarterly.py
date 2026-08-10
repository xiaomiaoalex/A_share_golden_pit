from datetime import date, datetime

import pytest

from src.screening.tier1_v2.quarterly import (
    build_quarterly_series,
    recent_quarter_window,
    ttm_parent_net_profit,
)
from tests.fixtures.tier1_synthetic import fact, improving_financial_facts


def test_cumulative_reports_are_reconstructed_to_single_quarters():
    series = build_quarterly_series(improving_financial_facts(), date(2026, 4, 30))
    indexed = {item.quarter: item for item in series}

    assert indexed[date(2025, 6, 30)].revenue_single == pytest.approx(105)
    assert indexed[date(2025, 9, 30)].revenue_single == pytest.approx(105)
    assert indexed[date(2025, 12, 31)].revenue_single == pytest.approx(110)
    assert indexed[date(2026, 3, 31)].revenue_single == pytest.approx(115)


def test_recent_window_crosses_year_and_has_strictly_improving_yoy():
    series = build_quarterly_series(improving_financial_facts(), date(2026, 4, 30))
    window = recent_quarter_window(series, 3)

    assert [item.quarter for item in window] == [
        date(2025, 9, 30),
        date(2025, 12, 31),
        date(2026, 3, 31),
    ]
    assert [item.revenue_yoy for item in window] == pytest.approx([0.05, 0.10, 0.15])
    assert [item.parent_np_yoy for item in window] == pytest.approx([0.05, 0.10, 0.15])


def test_future_announcement_is_excluded_at_as_of_date():
    facts = improving_financial_facts()
    facts[-1] = fact(date(2026, 3, 31), 115, 11.5, date(2026, 5, 1))
    series = build_quarterly_series(facts, date(2026, 4, 30))

    assert date(2026, 3, 31) not in {item.quarter for item in series}


def test_future_revision_is_excluded_by_pure_quarterly_calculator():
    facts = improving_financial_facts()
    facts[-1] = type(facts[-1])(
        **{
            **facts[-1].__dict__,
            "revision_at": datetime(2026, 5, 1),
        }
    )
    series = build_quarterly_series(facts, date(2026, 4, 30))
    assert date(2026, 3, 31) not in {item.quarter for item in series}


def test_missing_cumulative_predecessor_does_not_get_skipped():
    facts = [
        fact(date(2024, 6, 30), 200, 20),
        fact(date(2025, 6, 30), 220, 22),
    ]
    series = build_quarterly_series(facts, date(2025, 8, 31))
    metric = next(item for item in series if item.quarter == date(2025, 6, 30))

    assert metric.revenue_single is None
    assert metric.parent_np_single is None
    assert metric.missing_fields


def test_ttm_requires_four_consecutive_single_quarters():
    series = build_quarterly_series(improving_financial_facts(), date(2026, 4, 30))
    # 2025Q2/Q3/Q4 + 2026Q1 = 10.5 + 10.5 + 11 + 11.5
    assert ttm_parent_net_profit(series) == pytest.approx(43.5)
    incomplete = [item for item in series if item.quarter != date(2025, 12, 31)]
    assert ttm_parent_net_profit(incomplete) is None
