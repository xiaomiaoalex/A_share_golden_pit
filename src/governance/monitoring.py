"""Deterministic signal drift and realized-performance monitoring."""

from __future__ import annotations

import math
from collections import Counter
from typing import Iterable, Mapping


def signal_drift(
    baseline_scores: Iterable[float], current_scores: Iterable[float]
) -> dict:
    baseline, current = list(baseline_scores), list(current_scores)
    if not baseline or not current:
        raise ValueError("漂移监控需要基线和当前样本")
    baseline_mean = sum(baseline) / len(baseline)
    current_mean = sum(current) / len(current)
    baseline_variance = sum((value - baseline_mean) ** 2 for value in baseline) / len(baseline)
    standardized_shift = (
        abs(current_mean - baseline_mean) / math.sqrt(baseline_variance)
        if baseline_variance > 0
        else (0.0 if current_mean == baseline_mean else float("inf"))
    )
    return {
        "baseline_mean": baseline_mean,
        "current_mean": current_mean,
        "standardized_shift": standardized_shift,
        "status": "ALERT" if standardized_shift > 1.0 else "OK",
    }


def performance_deviation(
    expected_returns: Iterable[float], realized_returns: Iterable[float]
) -> dict:
    expected, realized = list(expected_returns), list(realized_returns)
    if len(expected) != len(realized) or not expected:
        raise ValueError("实际表现监控需要等长非空序列")
    errors = [actual - forecast for forecast, actual in zip(expected, realized)]
    mean_error = sum(errors) / len(errors)
    hit_rate = sum(
        (forecast >= 0) == (actual >= 0)
        for forecast, actual in zip(expected, realized)
    ) / len(expected)
    return {
        "mean_error": mean_error,
        "hit_rate": hit_rate,
        "status": "ALERT" if hit_rate < 0.5 else "OK",
    }


def conflict_summary(signals: Iterable[Mapping]) -> dict:
    counts = Counter((item["security_id"], item["direction"]) for item in signals)
    return {"counts": {f"{security}:{direction}": value for (security, direction), value in counts.items()}}
