"""Reproducible release identity for golden-pit decisions."""

from __future__ import annotations

import hashlib
import os
import platform
from importlib import metadata
from pathlib import Path
from typing import Any

from .config import Tier1Config

STRATEGY_ROOT = Path(__file__).resolve().parent
TRACKED_SUFFIXES = {".py", ".json", ".md"}
DEPENDENCIES = ("akshare", "baostock", "tushare", "pandas", "jsonschema")


def strategy_fingerprint() -> str:
    """Hash executable rules and bundled strategy contracts in stable path order."""
    digest = hashlib.sha256()
    for path in sorted(
        item
        for item in STRATEGY_ROOT.rglob("*")
        if item.is_file()
        and item.suffix.lower() in TRACKED_SUFFIXES
        and "__pycache__" not in item.parts
    ):
        digest.update(path.relative_to(STRATEGY_ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _dependency_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for package in DEPENDENCIES:
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = "not-installed"
    return versions


def build_release_manifest(config: Tier1Config | None = None) -> dict[str, Any]:
    active = config or Tier1Config()
    fingerprint = strategy_fingerprint()
    return {
        "strategy_id": "golden-pit",
        "calculation_version": active.calculation_version,
        "strategy_fingerprint": fingerprint,
        "source_revision": os.environ.get("PLATFORM_RELEASE_SHA")
        or os.environ.get("GITHUB_SHA")
        or "working-tree",
        "python": platform.python_version(),
        "dependencies": _dependency_versions(),
        "config": active.to_dict(),
    }


def strategy_release_version() -> str:
    config = Tier1Config()
    return f"{config.calculation_version}+{strategy_fingerprint()[:10]}"
