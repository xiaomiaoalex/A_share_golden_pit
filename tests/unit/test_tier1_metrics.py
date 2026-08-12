from datetime import date

import pytest

from src.screening.tier1_v2.contracts import CorporateAction, DividendEvent
from src.screening.tier1_v2.metrics import (
    calculate_latest_fiscal_year_dividend,
    calculate_dividend_ttm,
    compute_self_pe_ttm,
    select_pe_ttm,
)


def _dividend(ex_date, report_period, cash, *, source="synthetic"):
    return DividendEvent(
        symbol="000001",
        ex_date=ex_date,
        report_period=report_period,
        raw_cash_per_share_pre_tax=cash,
        status="实施分配",
        source=source,
    )


def test_latest_complete_fiscal_year_excludes_prior_annual_dividend():
    result = calculate_latest_fiscal_year_dividend(
        events=[
            _dividend(date(2025, 8, 20), date(2024, 12, 31), 0.71914),
            _dividend(date(2026, 7, 14), date(2025, 12, 31), 0.55581),
        ],
        actions=[],
        as_of_date=date(2026, 8, 10),
        close_price=16.37,
    )

    assert result.fiscal_year == 2025
    assert result.adjusted_per_share == pytest.approx(0.55581)
    assert result.dividend_yield == pytest.approx(0.55581 / 16.37)
    assert result.overlapping_annual_report_periods == (
        date(2024, 12, 31),
        date(2025, 12, 31),
    )


def test_latest_fiscal_year_sums_interim_special_and_annual_and_deduplicates():
    events = [
        _dividend(date(2025, 10, 1), date(2025, 6, 30), 0.2),
        _dividend(date(2026, 1, 5), date(2025, 9, 30), 0.1),
        _dividend(date(2026, 6, 1), date(2025, 12, 31), 0.4),
        _dividend(date(2026, 6, 1), date(2025, 12, 31), 0.4, source="duplicate"),
    ]
    result = calculate_latest_fiscal_year_dividend(
        events=events,
        actions=[],
        as_of_date=date(2026, 8, 10),
        close_price=10,
    )

    assert result.fiscal_year == 2025
    assert result.adjusted_per_share == pytest.approx(0.7)
    assert result.dividend_yield == pytest.approx(0.07)
    assert len(result.events) == 3


def test_missing_report_period_cannot_produce_fiscal_year_yield():
    result = calculate_latest_fiscal_year_dividend(
        events=[_dividend(date(2026, 6, 1), None, 0.8)],
        actions=[],
        as_of_date=date(2026, 8, 10),
        close_price=10,
    )

    assert result.missing_report_period is True
    assert result.dividend_yield is None


def test_self_pe_requires_positive_profit_and_market_cap():
    assert compute_self_pe_ttm(120, 10) == pytest.approx(12)
    assert compute_self_pe_ttm(120, 0) is None
    assert compute_self_pe_ttm(120, -1) is None
    assert compute_self_pe_ttm(None, 10) is None


def test_current_uses_supplier_and_historical_uses_point_in_time_self_pe():
    current = select_pe_ttm(
        supplier_pe_ttm=12,
        self_pe_ttm=13,
        historical=False,
        mismatch_warning_ratio=0.05,
    )
    historical = select_pe_ttm(
        supplier_pe_ttm=12,
        self_pe_ttm=13,
        historical=True,
        mismatch_warning_ratio=0.05,
    )

    assert current.selected == 12
    assert current.method == "SUPPLIER_FIELD_CONTRACT_VALIDATED"
    assert historical.selected == 13
    assert historical.method == "POINT_IN_TIME_SELF_COMPUTED"
    assert current.warnings


def test_dividend_is_adjusted_for_later_share_split_and_raw_is_preserved():
    event = DividendEvent(
        symbol="000001",
        ex_date=date(2025, 9, 1),
        raw_cash_per_share_pre_tax=1.0,
        status="实施分配",
        source="synthetic",
    )
    action = CorporateAction(
        symbol="000001",
        effective_date=date(2025, 10, 1),
        share_factor=2.0,
        source="synthetic",
    )
    result = calculate_dividend_ttm(
        events=[event], actions=[action], as_of_date=date(2026, 8, 31), close_price=10
    )

    assert result.raw_per_share == pytest.approx(1.0)
    assert result.adjusted_per_share == pytest.approx(0.5)
    assert result.dividend_yield_ttm == pytest.approx(0.05)


def test_provider_adjusted_dividend_is_not_adjusted_twice():
    event = DividendEvent(
        symbol="000001",
        ex_date=date(2025, 9, 1),
        raw_cash_per_share_pre_tax=1.0,
        status="实施分配",
        source="synthetic",
        provider_adjusted=True,
    )
    action = CorporateAction(
        symbol="000001",
        effective_date=date(2025, 10, 1),
        share_factor=2.0,
        source="synthetic",
    )
    result = calculate_dividend_ttm(
        events=[event], actions=[action], as_of_date=date(2026, 8, 31), close_price=10
    )

    assert result.adjusted_per_share == pytest.approx(1.0)
    assert result.dividend_yield_ttm == pytest.approx(0.10)


def test_dividend_window_excludes_exactly_one_calendar_year_old_event():
    event = DividendEvent(
        symbol="000001",
        ex_date=date(2025, 8, 31),
        raw_cash_per_share_pre_tax=1.0,
        status="实施分配",
        source="synthetic",
    )
    result = calculate_dividend_ttm(
        events=[event], actions=[], as_of_date=date(2026, 8, 31), close_price=10
    )
    assert result.raw_per_share == 0
    assert result.dividend_yield_ttm == 0


@pytest.mark.parametrize(
    "event",
    [
        DividendEvent(
            symbol="000001",
            ex_date=date(2026, 1, 1),
            raw_cash_per_share_pre_tax=1,
            status="预案",
            source="synthetic",
        ),
        DividendEvent(
            symbol="000001",
            ex_date=date(2026, 1, 1),
            raw_cash_per_share_pre_tax=1,
            status="实施分配",
            source="synthetic",
            announcement_date=date(2026, 9, 1),
        ),
    ],
)
def test_dividend_excludes_unimplemented_or_future_announced_events(event):
    result = calculate_dividend_ttm(
        events=[event], actions=[], as_of_date=date(2026, 8, 10), close_price=10
    )
    assert result.raw_per_share == 0
    assert result.dividend_yield_ttm == 0
