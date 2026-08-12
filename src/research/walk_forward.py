"""Framework-neutral walk-forward splitting and rank IC."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence


@dataclass(frozen=True)
class WalkForwardFold:
    train: tuple[date, ...]
    validation: tuple[date, ...]
    test: tuple[date, ...]


def build_walk_forward_folds(
    dates: Sequence[date], *, train_size: int, validation_size: int, test_size: int
) -> tuple[WalkForwardFold, ...]:
    ordered = tuple(sorted(set(dates)))
    if min(train_size, validation_size, test_size) < 1:
        raise ValueError("walk-forward 各窗口必须为正数")
    width = train_size + validation_size + test_size
    folds = []
    for offset in range(0, len(ordered) - width + 1, test_size):
        train_end = offset + train_size
        validation_end = train_end + validation_size
        folds.append(
            WalkForwardFold(
                train=ordered[offset:train_end],
                validation=ordered[train_end:validation_end],
                test=ordered[validation_end : validation_end + test_size],
            )
        )
    return tuple(folds)


def rank_ic(scores: Sequence[float], returns: Sequence[float]) -> float:
    if len(scores) != len(returns) or len(scores) < 2:
        raise ValueError("Rank IC 需要等长且至少两个样本")

    def ranks(values: Sequence[float]) -> list[float]:
        ordered = sorted((value, index) for index, value in enumerate(values))
        result = [0.0] * len(values)
        position = 0
        while position < len(ordered):
            end = position + 1
            while end < len(ordered) and ordered[end][0] == ordered[position][0]:
                end += 1
            average = (position + 1 + end) / 2
            for _, index in ordered[position:end]:
                result[index] = average
            position = end
        return result

    x, y = ranks(scores), ranks(returns)
    mean_x, mean_y = sum(x) / len(x), sum(y) / len(y)
    covariance = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y))
    variance_x = sum((a - mean_x) ** 2 for a in x)
    variance_y = sum((b - mean_y) ** 2 for b in y)
    if variance_x == 0 or variance_y == 0:
        raise ValueError("Rank IC 无法用于常量序列")
    return covariance / (variance_x * variance_y) ** 0.5
