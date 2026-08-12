"""Stable, serializable contracts shared by strategies and research adapters."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any, Mapping


class SignalDirection(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True)
class StrategyParameters:
    schema_version: str
    values: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.schema_version.strip():
            raise ValueError("策略参数必须声明 schema_version")


@dataclass(frozen=True)
class StrategyReleaseManifest:
    release_id: str
    strategy_id: str
    version: str
    git_sha: str
    strategy_hash: str
    config_hash: str
    dependency_hash: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StrategyRunContext:
    run_id: str
    strategy_id: str
    release_id: str
    as_of_date: date
    data_snapshot_id: str
    parameters: StrategyParameters
    random_seed: int = 0


@dataclass(frozen=True)
class SignalRecord:
    signal_id: str
    run_id: str
    strategy_id: str
    release_id: str
    security_id: str
    symbol: str
    as_of_date: date
    direction: SignalDirection
    score: float
    rank: int
    confidence: float
    valid_until: date
    attribution: Mapping[str, Any]
    data_snapshot_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("信号置信度必须在 0 到 1 之间")
        if self.rank < 1:
            raise ValueError("信号排名必须从 1 开始")
        if self.valid_until < self.as_of_date:
            raise ValueError("信号有效期不能早于点时日期")
        if not self.attribution:
            raise ValueError("信号必须包含候选归因")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
