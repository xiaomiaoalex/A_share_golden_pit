"""Deterministic factor diagnostics independent of Qlib storage."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Sequence

from .walk_forward import rank_ic


@dataclass(frozen=True)
class FactorDiagnostics:
    ic: float
    rank_ic: float
    autocorrelation: float
    turnover: float
    group_returns: tuple[float, ...]

    def as_payload(self) -> dict:
        return asdict(self)


def _correlation(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        raise ValueError("相关性需要等长且至少两个样本")
    mean_left, mean_right = sum(left) / len(left), sum(right) / len(right)
    numerator = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    denominator = math.sqrt(sum((a - mean_left) ** 2 for a in left)) * math.sqrt(
        sum((b - mean_right) ** 2 for b in right)
    )
    if denominator == 0:
        raise ValueError("相关性无法用于常量序列")
    return numerator / denominator


def analyze_factor(
    scores: Sequence[float],
    forward_returns: Sequence[float],
    prior_scores: Sequence[float],
    *,
    groups: int = 5,
) -> FactorDiagnostics:
    if len(scores) != len(forward_returns) or len(scores) != len(prior_scores):
        raise ValueError("因子诊断输入必须等长")
    if groups < 2 or len(scores) < groups:
        raise ValueError("分组数量无效或样本不足")
    ordered = sorted(range(len(scores)), key=lambda index: scores[index])
    buckets = []
    for group in range(groups):
        start = group * len(scores) // groups
        end = (group + 1) * len(scores) // groups
        values = [forward_returns[index] for index in ordered[start:end]]
        buckets.append(sum(values) / len(values))
    current_top = set(ordered[-max(1, len(scores) // groups) :])
    prior_ordered = sorted(range(len(prior_scores)), key=lambda index: prior_scores[index])
    prior_top = set(prior_ordered[-max(1, len(scores) // groups) :])
    turnover = 1.0 - len(current_top & prior_top) / len(current_top | prior_top)
    return FactorDiagnostics(
        ic=_correlation(scores, forward_returns),
        rank_ic=rank_ic(scores, forward_returns),
        autocorrelation=_correlation(prior_scores, scores),
        turnover=turnover,
        group_returns=tuple(buckets),
    )
