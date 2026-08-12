import pytest

from src.backtest import compare_execution_results
from src.governance import performance_deviation, signal_drift
from src.portfolio import risk_report
from src.research import analyze_factor


def test_factor_diagnostics_include_ic_groups_autocorrelation_and_turnover():
    result = analyze_factor(
        [1, 2, 3, 4, 5],
        [0.01, 0.02, 0.03, 0.04, 0.05],
        [1, 2, 3, 5, 4],
        groups=5,
    )

    assert result.ic == pytest.approx(1.0)
    assert result.rank_ic == pytest.approx(1.0)
    assert result.group_returns == (0.01, 0.02, 0.03, 0.04, 0.05)
    assert result.turnover == 1.0


def test_dual_engine_differences_explain_fills_and_fees():
    comparison = compare_execution_results(
        [{"order_id": "o1", "status": "FILLED", "filled_quantity": 100, "price": 10, "commission": 3, "stamp_tax": 0, "reason": None}],
        [{"order_id": "o1", "status": "PARTIAL", "filled_quantity": 50, "price": 10, "commission": 2, "stamp_tax": 0, "reason": "CAPACITY"}],
    )

    assert comparison["differences"][0]["reason"] == "FILL_DIFFERENCE"
    assert "commission" in comparison["differences"][0]["fields"]


def test_portfolio_risk_contribution_and_stress_are_deterministic():
    result = risk_report(
        {"a": 0.6, "b": 0.4},
        {"a": 0.2, "b": 0.1},
        {"market_crash": {"a": -0.2, "b": -0.1}},
    )

    assert sum(result["risk_contributions"].values()) == pytest.approx(1.0)
    assert result["stress_returns"]["market_crash"] == pytest.approx(-0.16)
    assert result["concentration_hhi"] == pytest.approx(0.52)


def test_drift_and_performance_deviation_raise_deterministic_alerts():
    drift = signal_drift([1, 2, 3, 4], [8, 9, 10, 11])
    performance = performance_deviation([0.1, 0.2, -0.1], [-0.1, -0.2, 0.1])

    assert drift["status"] == "ALERT"
    assert performance["status"] == "ALERT"
    assert performance["hit_rate"] == 0.0
