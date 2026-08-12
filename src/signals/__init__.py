"""Provider-neutral strategy signal contracts."""

from .contracts import (
    SignalDirection,
    SignalRecord,
    StrategyParameters,
    StrategyReleaseManifest,
    StrategyRunContext,
)
from .materialization import (
    materialize_golden_pit_signals,
    materialize_high_dividend_signals,
)
from .repository import SignalRepository

__all__ = [
    "SignalDirection",
    "SignalRecord",
    "StrategyParameters",
    "StrategyReleaseManifest",
    "StrategyRunContext",
    "SignalRepository",
    "materialize_golden_pit_signals",
    "materialize_high_dividend_signals",
]
