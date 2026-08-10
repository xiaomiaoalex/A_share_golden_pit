"""Command entry point for the multi-strategy stock-screening platform."""

from __future__ import annotations

import argparse
import sys

from config.settings import settings
from src.strategies import build_strategy_registry
from src.strategies.golden_pit.cli import (
    _formal_workflow_command,
    _load_universe_file,
    _normalize_symbol,
    build_parser,
)


def _print_strategy_catalog() -> None:
    registry = build_strategy_registry(settings.DB_PATH)
    for module in registry.modules():
        descriptor = module.descriptor
        print(f"{descriptor.strategy_id}\t{descriptor.name}\t{descriptor.version}")


def main() -> None:
    """Route platform commands while preserving the historical Golden Pit CLI."""
    if len(sys.argv) >= 2 and sys.argv[1] == "migrate":
        parser = argparse.ArgumentParser(description="应用选股策略平台数据库迁移")
        parser.add_argument("--db", default=str(settings.DB_PATH))
        args = parser.parse_args(sys.argv[2:])
        from src.strategies.golden_pit.persistence.tier1_repository import (
            Tier1Repository,
        )

        Tier1Repository(args.db).migrate_all()
        print(f"已应用平台数据库迁移: {args.db}")
        return
    if len(sys.argv) >= 3 and sys.argv[1:3] == ["strategy", "list"]:
        _print_strategy_catalog()
        return
    if len(sys.argv) >= 3 and sys.argv[1] == "strategy":
        module = build_strategy_registry(settings.DB_PATH).get(sys.argv[2])
        cli_main = getattr(module, "cli_main", None)
        if not callable(cli_main):
            raise SystemExit(f"策略未提供 CLI: {sys.argv[2]}")
        cli_main(sys.argv[3:])
        return
    from src.strategies.golden_pit.cli import main as compatibility_main

    compatibility_main()


if __name__ == "__main__":
    main()


__all__ = [
    "_formal_workflow_command",
    "_load_universe_file",
    "_normalize_symbol",
    "build_parser",
    "main",
]
