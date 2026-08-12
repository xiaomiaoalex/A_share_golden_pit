"""Portfolio risk contribution and deterministic stress scenarios."""

from __future__ import annotations

from typing import Mapping


def risk_report(
    weights: Mapping[str, float],
    volatility: Mapping[str, float],
    scenarios: Mapping[str, Mapping[str, float]],
) -> dict:
    marginal = {
        security: abs(weight) * volatility.get(security, 0.0)
        for security, weight in weights.items()
    }
    total = sum(marginal.values())
    contributions = {
        security: value / total if total else 0.0 for security, value in marginal.items()
    }
    stress = {
        scenario: sum(weight * shocks.get(security, 0.0) for security, weight in weights.items())
        for scenario, shocks in scenarios.items()
    }
    return {
        "risk_contributions": contributions,
        "stress_returns": stress,
        "concentration_hhi": sum(weight * weight for weight in weights.values()),
    }
