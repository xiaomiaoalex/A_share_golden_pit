from datetime import date, timedelta

from src.backtest import BacktestSpecification, MarketBar, OrderIntent
from src.backtest.contracts import OrderSide
from src.integrations import CVXPYAdapter, OpenBBAdapter, QlibAdapter, VnpyAdapter
from src.portfolio import ConstraintSet
from src.signals import (
    materialize_golden_pit_signals,
    materialize_high_dividend_signals,
)


def test_golden_pit_results_materialize_to_ranked_unified_signals():
    signals = materialize_golden_pit_signals(
        [
            {"symbol": "000002", "screen_status": "PASS", "selected_pe_ttm": 8, "latest_fiscal_year_dividend_yield": 0.05, "decision_id": "d2"},
            {"symbol": "000001", "screen_status": "PASS", "selected_pe_ttm": 10, "latest_fiscal_year_dividend_yield": 0.07, "decision_id": "d1"},
            {"symbol": "000003", "screen_status": "REJECT", "selected_pe_ttm": 5, "latest_fiscal_year_dividend_yield": 0.1},
        ],
        run_id="run-1",
        release_id="release-1",
        data_snapshot_id="snapshot-1",
        as_of_date=date(2026, 8, 12),
    )

    assert [item.symbol for item in signals] == ["000001", "000002"]
    assert signals[0].attribution["decision_id"] == "d1"
    assert signals[0].rank == 1


def test_high_dividend_strategy_has_deterministic_executable_screen():
    signals = materialize_high_dividend_signals(
        [
            {"symbol": "600001", "pe_ttm": 10, "dividend_yield": 0.05},
            {"symbol": "600002", "pe_ttm": 15, "dividend_yield": 0.08},
            {"symbol": "600003", "pe_ttm": 8, "dividend_yield": 0.07},
        ],
        run_id="run-hd",
        release_id="release-hd",
        data_snapshot_id="snapshot-hd",
        as_of_date=date(2026, 8, 12),
    )

    assert [item.symbol for item in signals] == ["600003", "600001"]
    assert signals[0].strategy_id == "high-dividend"
    assert signals[0].attribution["thresholds"]["max_pe"] == 12.0


def test_framework_adapters_consume_contract_payloads_only():
    qlib = QlibAdapter()
    dataset = qlib.build_dataset(
        [
            {"security_id": "s1", "trade_date": "2026-08-12", "factor": 1.0, "return": 0.1},
            {"security_id": "s2", "trade_date": "2026-08-12", "factor": 2.0, "return": 0.2},
        ],
        feature_fields=("factor",),
        label_field="return",
    )
    assert dataset["access_mode"] == "ARTIFACT_ONLY"
    assert qlib.evaluate_rank_ic([1, 2], [0.1, 0.2]) == 1.0

    specification = BacktestSpecification(
        "bt", "release", "snapshot", date(2026, 1, 1), date(2026, 12, 31), 1_000_000
    )
    execution = VnpyAdapter().simulate(
        specification,
        OrderIntent("order", "s1", OrderSide.BUY, 100, date(2026, 8, 10)),
        MarketBar("s1", date(2026, 8, 10) + timedelta(days=1), 10, 10000),
    )
    assert execution["status"] == "FILLED"

    portfolio = CVXPYAdapter().construct(
        {"s1": 1.0, "s2": 1.0},
        {"s1": "a", "s2": "b"},
        {"s1": 10, "s2": 10},
        ConstraintSet(max_weight=0.6, max_industry_weight=0.6),
    )
    assert portfolio.status == "FEASIBLE"

    supplemental = OpenBBAdapter().normalize(
        [{"as_of_date": "2026-08-12", "value": 101.5}], source="macro"
    )
    assert supplemental["access_mode"] == "SUPPLEMENTAL_ARTIFACT_ONLY"
