#!/usr/bin/env python3
"""Multi-strategy platform deployment checks."""

from __future__ import annotations

import importlib
import json
import sys

from config.settings import settings
from src.data.point_in_time.provider_factory import build_point_in_time_provider
from src.strategies.golden_pit.config import Tier1Config
from src.strategies.golden_pit.persistence.tier3_repository import Tier3Repository
from src.strategies.golden_pit.resources import (
    EVIDENCE_SCHEMA,
    RISK_INPUT_SCHEMA,
    RISK_RULES,
)

REQUIRED_MODULES = ("pandas", "akshare", "baostock", "tushare", "jsonschema")
SCHEMAS = (EVIDENCE_SCHEMA, RISK_INPUT_SCHEMA, RISK_RULES)


def check_python() -> None:
    if sys.version_info < (3, 10):
        raise RuntimeError("需要 Python 3.10+")


def check_dependencies() -> None:
    missing = []
    for module in REQUIRED_MODULES:
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(module)
    if missing:
        raise RuntimeError("缺少依赖: " + ", ".join(missing))


def check_schemas() -> None:
    for path in SCHEMAS:
        json.loads(path.read_text(encoding="utf-8"))


def check_database() -> None:
    repository = Tier3Repository(settings.DB_PATH)
    repository.migrate()
    with repository.connect() as connection:
        versions = {
            row[0]
            for row in connection.execute(
                "SELECT version FROM schema_migrations"
            ).fetchall()
        }
    expected = {
        "001_tier1_v2",
        "002_tier1_data_quality",
        "003_tier2_human_ai",
        "004_tier3_risk_filter",
        "005_tier1_resume",
        "006_strategy_identity",
    }
    if not expected.issubset(versions):
        raise RuntimeError(f"数据库迁移不完整: {sorted(expected - versions)}")


def check_provider_configuration() -> None:
    provider = build_point_in_time_provider(Tier1Config())
    provider.close()


def main() -> int:
    checks = (
        ("Python", check_python),
        ("依赖", check_dependencies),
        ("Schema", check_schemas),
        ("数据库迁移", check_database),
        ("数据源配置", check_provider_configuration),
    )
    failed = []
    for name, check in checks:
        try:
            check()
        except Exception as exc:  # 部署自检需要汇总所有失败项
            failed.append((name, str(exc)))
            print(f"[FAIL] {name}: {exc}")
        else:
            print(f"[OK] {name}")
    if failed:
        return 1
    print("系统就绪：python main.py strategy golden-pit workflow --help")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
