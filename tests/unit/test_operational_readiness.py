import sqlite3

import pytest

from scripts.backup_database import backup_database
from scripts.dependency_inventory import inventory
from src.strategies.golden_pit.persistence.tier1_repository import Tier1Repository


def test_backup_is_recoverable_and_preserves_migrations(tmp_path):
    source = tmp_path / "source.db"
    backup = tmp_path / "backups" / "source.backup.db"
    Tier1Repository(source).migrate_all()

    manifest = backup_database(source, backup)

    assert manifest["integrity"] == "ok"
    assert manifest["size_bytes"] > 0
    with sqlite3.connect(backup) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_migrations"
        ).fetchone()[0] >= 13


def test_backup_timeout_removes_partial_destination(monkeypatch, tmp_path):
    source = tmp_path / "source.db"
    backup = tmp_path / "source.backup.db"
    Tier1Repository(source).migrate_all()

    class Clock:
        value = 0.0

        def __call__(self):
            self.value += 1.0
            return self.value

    monkeypatch.setattr("scripts.backup_database.time.monotonic", Clock())

    with pytest.raises(TimeoutError, match="已安全终止"):
        backup_database(source, backup, timeout_seconds=0.5)

    assert not backup.exists()


def test_direct_dependency_inventory_has_versions_and_licenses():
    packages = inventory()

    assert {item["package"] for item in packages} >= {"duckdb", "pandas", "akshare"}
    assert all(item["version"] for item in packages)
    assert all(item["license"] for item in packages)


def test_docker_context_excludes_runtime_data_and_credentials():
    patterns = {
        line.strip()
        for line in open(".dockerignore", encoding="utf-8")
        if line.strip() and not line.startswith("#")
    }

    assert {"data", "output", "logs", ".env", ".git", ".workbuddy"} <= patterns
