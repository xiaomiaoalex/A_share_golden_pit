from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping


class PortfolioMethod(StrEnum):
    EQUAL_WEIGHT = "EQUAL_WEIGHT"
    SIGNAL_WEIGHTED = "SIGNAL_WEIGHTED"
    RISK_PARITY = "RISK_PARITY"
    MEAN_VARIANCE = "MEAN_VARIANCE"
    BLACK_LITTERMAN = "BLACK_LITTERMAN"
    HRP = "HRP"


@dataclass(frozen=True)
class ConstraintSet:
    max_weight: float = 0.1
    max_industry_weight: float = 0.3
    min_liquidity: float = 0.0
    max_turnover: float = 1.0
    max_beta: float | None = None
    max_volatility: float | None = None


@dataclass(frozen=True)
class PortfolioResult:
    status: str
    weights: Mapping[str, float]
    reasons: tuple[str, ...]


class PortfolioConstructor:
    def construct(
        self,
        scores: Mapping[str, float],
        industries: Mapping[str, str],
        liquidity: Mapping[str, float],
        constraints: ConstraintSet,
        *,
        method: PortfolioMethod = PortfolioMethod.SIGNAL_WEIGHTED,
        volatility: Mapping[str, float] | None = None,
        expected_returns: Mapping[str, float] | None = None,
        market_weights: Mapping[str, float] | None = None,
        views: Mapping[str, float] | None = None,
        beta: Mapping[str, float] | None = None,
        current_weights: Mapping[str, float] | None = None,
    ) -> PortfolioResult:
        eligible = {
            security: max(score, 0.0)
            for security, score in scores.items()
            if liquidity.get(security, 0.0) >= constraints.min_liquidity
        }
        if not eligible or sum(eligible.values()) <= 0:
            return PortfolioResult("INFEASIBLE", {}, ("NO_ELIGIBLE_POSITIVE_SIGNAL",))
        if method == PortfolioMethod.EQUAL_WEIGHT:
            raw = {security: 1.0 for security in eligible}
        elif method in {PortfolioMethod.RISK_PARITY, PortfolioMethod.HRP}:
            risks = volatility or {}
            if any(risks.get(security, 0.0) <= 0 for security in eligible):
                return PortfolioResult("INFEASIBLE", {}, ("MISSING_POSITIVE_VOLATILITY",))
            raw = {security: 1.0 / risks[security] for security in eligible}
        elif method == PortfolioMethod.MEAN_VARIANCE:
            returns = expected_returns or {}
            risks = volatility or {}
            if any(risks.get(security, 0.0) <= 0 for security in eligible):
                return PortfolioResult("INFEASIBLE", {}, ("MISSING_POSITIVE_VOLATILITY",))
            raw = {
                security: max(returns.get(security, 0.0), 0.0) / risks[security] ** 2
                for security in eligible
            }
        elif method == PortfolioMethod.BLACK_LITTERMAN:
            market = market_weights or {}
            opinions = views or {}
            raw = {
                security: max(market.get(security, 0.0) + opinions.get(security, 0.0), 0.0)
                for security in eligible
            }
        else:
            raw = eligible
        if sum(raw.values()) <= 0:
            return PortfolioResult("INFEASIBLE", {}, ("NON_POSITIVE_OPTIMIZATION_INPUT",))
        weights = {security: value / sum(raw.values()) for security, value in raw.items()}
        if any(value > constraints.max_weight + 1e-12 for value in weights.values()):
            return PortfolioResult("INFEASIBLE", {}, ("MAX_WEIGHT_CONFLICT",))
        industry_weights: dict[str, float] = {}
        for security, weight in weights.items():
            industry = industries.get(security, "UNKNOWN")
            industry_weights[industry] = industry_weights.get(industry, 0.0) + weight
        if any(value > constraints.max_industry_weight + 1e-12 for value in industry_weights.values()):
            return PortfolioResult("INFEASIBLE", {}, ("INDUSTRY_LIMIT_CONFLICT",))
        if constraints.max_beta is not None:
            portfolio_beta = sum(
                weight * (beta or {}).get(security, 0.0)
                for security, weight in weights.items()
            )
            if portfolio_beta > constraints.max_beta + 1e-12:
                return PortfolioResult("INFEASIBLE", {}, ("BETA_LIMIT_CONFLICT",))
        if constraints.max_volatility is not None:
            approximate_volatility = sum(
                weight * (volatility or {}).get(security, 0.0)
                for security, weight in weights.items()
            )
            if approximate_volatility > constraints.max_volatility + 1e-12:
                return PortfolioResult("INFEASIBLE", {}, ("VOLATILITY_LIMIT_CONFLICT",))
        if current_weights is not None:
            securities = set(current_weights) | set(weights)
            turnover = sum(
                abs(weights.get(security, 0.0) - current_weights.get(security, 0.0))
                for security in securities
            ) / 2
            if turnover > constraints.max_turnover + 1e-12:
                return PortfolioResult("INFEASIBLE", {}, ("TURNOVER_LIMIT_CONFLICT",))
        return PortfolioResult("FEASIBLE", weights, ())
