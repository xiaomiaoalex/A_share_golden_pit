import sqlite3

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


def test_direct_dependency_inventory_has_versions_and_licenses():
    packages = inventory()

    assert {item["package"] for item in packages} >= {"duckdb", "pandas", "akshare"}
    assert all(item["version"] for item in packages)
    assert all(item["license"] for item in packages)
