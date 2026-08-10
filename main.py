"""Command entry point for the multi-strategy stock-screening platform."""

from __future__ import annotations

import sys

from src.strategies.golden_pit.cli import (
    _formal_workflow_command,
    _load_universe_file,
    _normalize_symbol,
    build_parser,
)
from src.strategies.golden_pit.cli import main as golden_pit_main
from src.strategies.golden_pit.module import GoldenPitStrategy


def _print_strategy_catalog() -> None:
    descriptor = GoldenPitStrategy.descriptor
    print(f"{descriptor.strategy_id}\t{descriptor.name}\t{descriptor.version}")


def main() -> None:
    """Route platform commands while preserving the historical Golden Pit CLI."""
    if len(sys.argv) >= 3 and sys.argv[1:3] == ["strategy", "list"]:
        _print_strategy_catalog()
        return
    if len(sys.argv) >= 3 and sys.argv[1] == "strategy":
        if sys.argv[2] != GoldenPitStrategy.descriptor.strategy_id:
            raise SystemExit(f"未知选股策略: {sys.argv[2]}")
        sys.argv = [sys.argv[0], *sys.argv[3:]]
    golden_pit_main()


if __name__ == "__main__":
    main()


__all__ = [
    "_formal_workflow_command",
    "_load_universe_file",
    "_normalize_symbol",
    "build_parser",
    "main",
]
