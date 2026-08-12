#!/usr/bin/env python3
"""Emit the direct dependency and license inventory used by release review."""

from __future__ import annotations

import json
from importlib import metadata

PACKAGES = ("akshare", "baostock", "tushare", "pandas", "jsonschema", "duckdb")
LICENSE_FALLBACKS = {"duckdb": "MIT"}


def inventory() -> list[dict[str, str]]:
    result = []
    for package in PACKAGES:
        distribution = metadata.distribution(package)
        result.append(
            {
                "package": package,
                "version": distribution.version,
                "license": distribution.metadata.get("License-Expression")
                or distribution.metadata.get("License")
                or LICENSE_FALLBACKS.get(package, "UNKNOWN"),
                "homepage": distribution.metadata.get("Home-page", ""),
            }
        )
    return result


if __name__ == "__main__":
    print(json.dumps(inventory(), ensure_ascii=False, indent=2))
