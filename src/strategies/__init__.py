"""Pluggable stock-selection strategies exposed by the research console."""

from .registry import StrategyRegistry, build_strategy_registry

__all__ = ["StrategyRegistry", "build_strategy_registry"]
