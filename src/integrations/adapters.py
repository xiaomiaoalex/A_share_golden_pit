"""Isolation adapters: third-party frameworks consume artifacts, never core tables."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable, Mapping

from src.backtest import (
    AshareExecutionSimulator,
    BacktestSpecification,
    MarketBar,
    OrderIntent,
)
from src.portfolio import ConstraintSet, PortfolioConstructor, PortfolioMethod
from src.research import build_walk_forward_folds, rank_ic


class QlibAdapter:
    """Convert point-in-time rows to a framework-neutral Qlib dataset payload."""

    def build_dataset(
        self, rows: Iterable[Mapping[str, Any]], *, feature_fields: tuple[str, ...], label_field: str
    ) -> dict[str, Any]:
        materialized = [dict(row) for row in rows]
        required = {"security_id", "trade_date", label_field, *feature_fields}
        if any(not required.issubset(row) for row in materialized):
            raise ValueError("Qlib 数据集缺少点时身份、日期、特征或标签")
        return {
            "records": materialized,
            "features": feature_fields,
            "label": label_field,
            "access_mode": "ARTIFACT_ONLY",
        }

    def evaluate_rank_ic(self, scores, returns) -> float:
        return rank_ic(scores, returns)

    def walk_forward(self, dates, *, train_size: int, validation_size: int, test_size: int):
        return build_walk_forward_folds(
            dates,
            train_size=train_size,
            validation_size=validation_size,
            test_size=test_size,
        )


class VnpyAdapter:
    """Event execution boundary using platform-owned A-share rules."""

    def simulate(
        self, specification: BacktestSpecification, order: OrderIntent, bar: MarketBar
    ) -> dict[str, Any]:
        return asdict(AshareExecutionSimulator(specification).execute(order, bar))


class CVXPYAdapter:
    """Optimization boundary with a deterministic safe fallback."""

    def construct(
        self,
        scores: Mapping[str, float],
        industries: Mapping[str, str],
        liquidity: Mapping[str, float],
        constraints: ConstraintSet,
        *,
        method: PortfolioMethod = PortfolioMethod.SIGNAL_WEIGHTED,
        **kwargs,
    ):
        return PortfolioConstructor().construct(
            scores, industries, liquidity, constraints, method=method, **kwargs
        )


class PyPortfolioOptAdapter(CVXPYAdapter):
    """Optional optimizer boundary sharing platform-owned constraints."""


class OpenBBAdapter:
    """Normalize supplemental data without granting core-table access."""

    def normalize(
        self, rows: Iterable[Mapping[str, Any]], *, source: str
    ) -> dict[str, Any]:
        materialized = [dict(row) for row in rows]
        if not source or any("as_of_date" not in row for row in materialized):
            raise ValueError("OpenBB 补充数据必须包含来源和点时日期")
        return {
            "source": source,
            "access_mode": "SUPPLEMENTAL_ARTIFACT_ONLY",
            "records": materialized,
        }
