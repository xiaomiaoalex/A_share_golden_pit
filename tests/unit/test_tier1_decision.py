from dataclasses import replace
from datetime import date

import pytest

from src.screening.tier1_v2.contracts import BusinessStatus, DataStatus
from src.screening.tier1_v2.decision import DecisionInput, evaluate_tier1
from tests.fixtures.tier1_synthetic import improving_window


def decision_input(**overrides):
    values = dict(
        symbol="000001",
        stock_name="测试股份",
        as_of_date=date(2026, 8, 10),
        price_date=date(2026, 8, 10),
        selected_pe_ttm=12.0,
        supplier_pe_ttm=12.0,
        self_pe_ttm=12.5,
        pe_selection_method="SUPPLIER_FIELD_CONTRACT_VALIDATED",
        dividend_yield_ttm=0.06,
        dividend_ttm_raw_per_share=0.6,
        dividend_ttm_adjusted_per_share=0.6,
        risk_warning=False,
        quarterly_window=improving_window(),
    )
    values.update(overrides)
    return DecisionInput(**values)


def test_all_strict_conditions_pass():
    result = evaluate_tier1(decision_input())
    assert result.business_status == BusinessStatus.PASS
    assert result.data_status == DataStatus.COMPLETE
    assert result.screen_status == "PASS"


@pytest.mark.parametrize(
    "field,value,condition",
    [
        ("selected_pe_ttm", 15.0, "pe_ttm"),
        ("dividend_yield_ttm", 0.05, "dividend_yield_ttm"),
        ("risk_warning", True, "risk_warning"),
    ],
)
def test_strict_boundaries_fail(field, value, condition):
    result = evaluate_tier1(decision_input(**{field: value}))
    assert result.screen_status == "FAIL"
    assert condition in {item["condition"] for item in result.failed_conditions}


def test_equal_adjacent_growth_fails():
    window = improving_window()
    window[2] = type(window[2])(
        **{**window[2].__dict__, "revenue_yoy": window[1].revenue_yoy}
    )
    result = evaluate_tier1(decision_input(quarterly_window=window))
    assert result.screen_status == "FAIL"
    assert "revenue_yoy_strictly_improving" in {
        item["condition"] for item in result.failed_conditions
    }


def test_negative_profit_base_enters_turnaround_watchlist():
    window = improving_window()
    window[1] = type(window[1])(
        **{**window[1].__dict__, "prior_year_parent_np_single": -1, "parent_np_yoy": None}
    )
    result = evaluate_tier1(decision_input(quarterly_window=window))
    assert result.business_status == BusinessStatus.NOT_COMPARABLE
    assert result.screen_status == "TURNAROUND_WATCHLIST"


def test_known_fail_wins_while_data_status_remains_partial():
    result = evaluate_tier1(
        decision_input(
            selected_pe_ttm=15,
            dividend_yield_ttm=None,
            risk_warning=None,
            quarterly_window=[],
            skipped_fields=["after_known_pe_fail"],
        )
    )
    assert result.business_status == BusinessStatus.FAIL
    assert result.data_status == DataStatus.PARTIAL
    assert result.screen_status == "FAIL"


def test_data_error_never_passes():
    result = evaluate_tier1(
        decision_input(selected_pe_ttm=None, error_fields=["market_snapshot"])
    )
    assert result.business_status == BusinessStatus.PENDING
    assert result.data_status == DataStatus.ERROR
    assert result.screen_status == "DATA_ERROR"


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), ""])
def test_invalid_pe_never_passes(bad):
    result = evaluate_tier1(decision_input(selected_pe_ttm=bad))
    assert result.screen_status != "PASS"


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), ""])
def test_invalid_dividend_never_passes(bad):
    result = evaluate_tier1(decision_input(dividend_yield_ttm=bad))
    assert result.screen_status == "PENDING_DATA"


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), ""])
def test_invalid_quarterly_growth_never_passes(bad):
    window = improving_window()
    window[1] = replace(window[1], revenue_yoy=bad, parent_np_yoy=bad)
    result = evaluate_tier1(decision_input(quarterly_window=window))
    assert result.screen_status == "PENDING_DATA"


@pytest.mark.parametrize("bad", [None, 0, 1, "", "false"])
def test_invalid_risk_warning_type_never_passes(bad):
    result = evaluate_tier1(decision_input(risk_warning=bad))
    assert result.screen_status == "PENDING_DATA"


def test_star_and_bse_symbols_are_not_excluded_by_board():
    assert evaluate_tier1(decision_input(symbol="688001")).screen_status == "PASS"
    assert evaluate_tier1(decision_input(symbol="920001")).screen_status == "PASS"
