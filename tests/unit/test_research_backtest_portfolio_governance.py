from datetime import date, timedelta

import pytest

from src.artifacts import ArtifactRepository
from src.backtest import (
    AshareExecutionSimulator,
    BacktestSpecification,
    MarketBar,
    OrderIntent,
)
from src.backtest.contracts import OrderSide
from src.governance import GovernanceService, ReleaseStatus
from src.portfolio import ConstraintSet, PortfolioConstructor, PortfolioMethod
from src.research import build_walk_forward_folds, rank_ic


def test_walk_forward_never_leaks_future_dates():
    dates = [date(2026, 1, 1) + timedelta(days=index) for index in range(10)]
    folds = build_walk_forward_folds(
        dates, train_size=4, validation_size=2, test_size=2
    )

    assert len(folds) == 2
    assert max(folds[0].train) < min(folds[0].validation) < min(folds[0].test)
    assert rank_ic([1, 2, 3, 4], [0.1, 0.2, -0.1, 0.4]) == pytest.approx(0.4)


def _specification():
    return BacktestSpecification(
        specification_id="bt-1",
        strategy_release_id="release-1",
        data_snapshot_id="snapshot-1",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        initial_cash=1_000_000,
    )


def test_ashare_execution_enforces_t1_limits_lots_liquidity_and_fees():
    simulator = AshareExecutionSimulator(_specification())
    signal_date = date(2026, 8, 10)
    buy = OrderIntent("buy", "security-1", OrderSide.BUY, 1050, signal_date)

    delayed = simulator.execute(
        buy, MarketBar("security-1", signal_date, 10.0, 100_000)
    )
    limit_up = simulator.execute(
        buy,
        MarketBar(
            "security-1", signal_date + timedelta(days=1), 10.0, 100_000, limit_up=True
        ),
    )
    filled = simulator.execute(
        buy,
        MarketBar("security-1", signal_date + timedelta(days=1), 10.0, 5_000),
    )
    sell = simulator.execute(
        OrderIntent("sell", "security-1", OrderSide.SELL, 500, signal_date),
        MarketBar("security-1", signal_date + timedelta(days=1), 10.0, 100_000),
    )

    assert delayed.reason == "SIGNAL_DELAY"
    assert limit_up.reason == "LIMIT_UP"
    assert filled.status == "PARTIAL"
    assert filled.filled_quantity == 500
    assert filled.commission == pytest.approx(1.5)
    assert sell.stamp_tax == pytest.approx(2.5)


def test_portfolio_hard_constraints_block_publication_candidate():
    constructor = PortfolioConstructor()
    infeasible = constructor.construct(
        {"a": 9.0, "b": 1.0},
        {"a": "bank", "b": "tech"},
        {"a": 100.0, "b": 100.0},
        ConstraintSet(max_weight=0.6, max_industry_weight=0.8),
    )
    feasible = constructor.construct(
        {"a": 1.0, "b": 1.0},
        {"a": "bank", "b": "tech"},
        {"a": 100.0, "b": 100.0},
        ConstraintSet(max_weight=0.6, max_industry_weight=0.8),
    )

    assert infeasible.status == "INFEASIBLE"
    assert infeasible.reasons == ("MAX_WEIGHT_CONFLICT",)
    assert feasible.status == "FEASIBLE"
    assert sum(feasible.weights.values()) == pytest.approx(1.0)


@pytest.mark.parametrize(
    "method,kwargs",
    [
        (PortfolioMethod.EQUAL_WEIGHT, {}),
        (PortfolioMethod.SIGNAL_WEIGHTED, {}),
        (PortfolioMethod.RISK_PARITY, {"volatility": {"a": 0.2, "b": 0.1}}),
        (PortfolioMethod.MEAN_VARIANCE, {"volatility": {"a": 0.2, "b": 0.1}, "expected_returns": {"a": 0.1, "b": 0.08}}),
        (PortfolioMethod.BLACK_LITTERMAN, {"market_weights": {"a": 0.5, "b": 0.5}, "views": {"a": 0.1, "b": 0.0}}),
        (PortfolioMethod.HRP, {"volatility": {"a": 0.2, "b": 0.1}}),
    ],
)
def test_portfolio_methods_share_hard_constraint_contract(method, kwargs):
    result = PortfolioConstructor().construct(
        {"a": 1.0, "b": 1.0},
        {"a": "bank", "b": "tech"},
        {"a": 100.0, "b": 100.0},
        ConstraintSet(max_weight=0.8, max_industry_weight=0.8),
        method=method,
        **kwargs,
    )

    assert result.status == "FEASIBLE"
    assert sum(result.weights.values()) == pytest.approx(1.0)


def test_portfolio_beta_volatility_and_turnover_are_hard_limits():
    constructor = PortfolioConstructor()
    common = (
        {"a": 1.0, "b": 1.0},
        {"a": "bank", "b": "tech"},
        {"a": 100.0, "b": 100.0},
    )
    beta = constructor.construct(
        *common,
        ConstraintSet(max_weight=0.8, max_industry_weight=0.8, max_beta=0.8),
        beta={"a": 1.0, "b": 1.0},
    )
    volatility = constructor.construct(
        *common,
        ConstraintSet(max_weight=0.8, max_industry_weight=0.8, max_volatility=0.15),
        volatility={"a": 0.2, "b": 0.2},
    )
    turnover = constructor.construct(
        *common,
        ConstraintSet(max_weight=0.8, max_industry_weight=0.8, max_turnover=0.1),
        current_weights={"a": 1.0, "b": 0.0},
    )

    assert beta.reasons == ("BETA_LIMIT_CONFLICT",)
    assert volatility.reasons == ("VOLATILITY_LIMIT_CONFLICT",)
    assert turnover.reasons == ("TURNOVER_LIMIT_CONFLICT",)


def test_release_requires_rbac_and_preserves_audit_history(tmp_path):
    governance = GovernanceService(tmp_path / "governance.db")
    governance.migrate()
    governance.create_release(
        release_id="release-1",
        object_type="STRATEGY",
        object_id="golden-pit",
        manifest={"git_sha": "abc", "tests": "passed"},
        actor="author",
    )
    with pytest.raises(PermissionError, match="RESEARCH_REVIEWER"):
        governance.transition(
            "release-1", ReleaseStatus.VALIDATED, actor="author"
        )
    governance.grant_role("reviewer", "RESEARCH_REVIEWER")
    governance.grant_role("manager", "RELEASE_MANAGER")
    governance.transition(
        "release-1", ReleaseStatus.VALIDATED, actor="reviewer"
    )
    governance.transition("release-1", ReleaseStatus.SHADOW, actor="manager")
    production = governance.transition(
        "release-1", ReleaseStatus.PRODUCTION, actor="manager"
    )

    assert production["status"] == "PRODUCTION"
    assert production["version"] == 4
    assert [item["action"] for item in governance.audit_timeline("golden-pit")] == [
        "CREATE_RELEASE",
        "RELEASE_VALIDATED",
        "RELEASE_SHADOW",
        "RELEASE_PRODUCTION",
    ]


def test_platform_artifacts_are_versioned_and_filterable(tmp_path):
    repository = ArtifactRepository(tmp_path / "artifacts.db")
    repository.migrate()
    repository.append(
        artifact_id="backtest-1",
        artifact_type="BACKTEST",
        status="DRAFT",
        payload={"annual_return": 0.1, "max_drawdown": -0.2},
        created_by="engine",
        strategy_id="golden-pit",
        release_id="release-1",
        data_snapshot_id="snapshot-1",
    )
    current = repository.append(
        artifact_id="backtest-1",
        artifact_type="BACKTEST",
        status="VALIDATED",
        payload={"annual_return": 0.1, "max_drawdown": -0.2, "qa": "passed"},
        created_by="validator",
        strategy_id="golden-pit",
        release_id="release-1",
        data_snapshot_id="snapshot-1",
    )

    assert current["version"] == 2
    assert current["status"] == "VALIDATED"
    assert repository.list_latest("BACKTEST")[0]["artifact_id"] == "backtest-1"
