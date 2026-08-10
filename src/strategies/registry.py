"""Strategy discovery and lookup without dependencies on concrete strategies."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .contracts import StrategyModule


class StrategyRegistry:
    """In-process registry; adding a strategy does not change the HTTP layer."""

    def __init__(self, modules: Iterable[StrategyModule] = ()) -> None:
        self._modules: dict[str, StrategyModule] = {}
        for module in modules:
            self.register(module)

    def register(self, module: StrategyModule) -> None:
        strategy_id = module.descriptor.strategy_id
        if strategy_id in self._modules:
            raise ValueError(f"选股策略重复注册: {strategy_id}")
        self._modules[strategy_id] = module

    def get(self, strategy_id: str) -> StrategyModule:
        try:
            return self._modules[strategy_id]
        except KeyError as exc:
            raise ValueError(f"未知选股策略: {strategy_id}") from exc

    def catalog(self) -> list[dict]:
        return [module.catalog_entry() for module in self._modules.values()]

    def modules(self) -> tuple[StrategyModule, ...]:
        return tuple(self._modules.values())


def build_strategy_registry(db_path: str | Path) -> StrategyRegistry:
    """Composition root for installed strategies."""
    from .golden_pit import GoldenPitStrategy

    return StrategyRegistry([GoldenPitStrategy(db_path)])
