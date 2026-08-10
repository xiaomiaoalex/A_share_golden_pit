import sqlite3
from datetime import date

import pytest

from config.tier1 import Tier1Config
from src.screening.tier1_v2.decision import evaluate_tier1
from src.storage.tier1_repository import Tier1Repository
from tests.unit.test_tier1_decision import decision_input


def test_additive_migration_and_rollback_preserve_legacy_table(tmp_path):
    db_path = tmp_path / "test.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE legacy_table(id INTEGER PRIMARY KEY, value TEXT)"
        )
        connection.execute("INSERT INTO legacy_table(value) VALUES ('keep')")

    repository = Tier1Repository(db_path)
    repository.migrate()
    with repository.connect() as connection:
        assert (
            connection.execute("SELECT value FROM legacy_table").fetchone()[0] == "keep"
        )
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='tier1_decisions'"
        ).fetchone()
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='data_quality_assessments'"
        ).fetchone()
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='source_verification_reports'"
        ).fetchone()

    repository.rollback_stage_a()
    with repository.connect() as connection:
        assert (
            connection.execute("SELECT value FROM legacy_table").fetchone()[0] == "keep"
        )
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name='tier1_decisions'"
            ).fetchone()
            is None
        )


def test_same_symbol_and_as_of_can_coexist_in_different_runs(tmp_path):
    repository = Tier1Repository(tmp_path / "test.db")
    config = Tier1Config()
    run1 = repository.begin_run(date(2026, 8, 10), config)
    run2 = repository.begin_run(date(2026, 8, 10), config)
    decision = evaluate_tier1(decision_input())
    repository.save_decision(run1, decision)
    repository.save_decision(run2, decision)

    assert len(repository.decisions(run1)) == 1
    assert len(repository.decisions(run2)) == 1
    assert run1 != run2


def test_decisions_after_rollback_returns_empty_instead_of_crashing(tmp_path):
    repository = Tier1Repository(tmp_path / "test.db")
    repository.migrate()
    repository.rollback_stage_a()
    assert repository.decisions("missing-run") == []


def test_source_verification_report_is_persisted(tmp_path):
    repository = Tier1Repository(tmp_path / "test.db")
    report = {
        "symbol": "000001",
        "as_of_date": "2026-08-10",
        "overall_verdict": "PASS",
        "providers": ["one", "two"],
        "responses": [],
        "checks": [{"field": "close_price", "verdict": "PASS"}],
        "note": "test",
    }

    verification_id = repository.save_source_verification(report)

    with repository.connect() as connection:
        row = connection.execute(
            "SELECT * FROM source_verification_reports WHERE verification_id=?",
            (verification_id,),
        ).fetchone()
    assert row["symbol"] == "000001"
    assert row["overall_verdict"] == "PASS"


def test_existing_stage_a_database_upgrades_to_quality_migration(tmp_path):
    db_path = tmp_path / "existing.db"
    repository = Tier1Repository(db_path)
    up_path = repository.project_root / "scripts" / "migrations" / "001_tier1_v2_up.sql"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(up_path.read_text(encoding="utf-8"))
        connection.execute(
            """
            INSERT INTO schema_migrations(version, applied_at, description)
            VALUES ('001_tier1_v2', '2026-08-10', 'existing')
            """
        )

    repository.migrate()
    repository.migrate()

    with repository.connect() as connection:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(screening_runs)")
        }
        versions = {
            row["version"]
            for row in connection.execute("SELECT version FROM schema_migrations")
        }
    assert "data_quality_summary_json" in columns
    assert versions == {"001_tier1_v2", "002_tier1_data_quality"}


def test_source_verification_cannot_bind_to_mismatched_run(tmp_path):
    repository = Tier1Repository(tmp_path / "test.db")
    run_id = repository.begin_run(date(2026, 8, 9), Tier1Config())
    report = {
        "symbol": "000001",
        "as_of_date": "2026-08-10",
        "overall_verdict": "PASS",
        "providers": ["one", "two"],
        "responses": [],
        "checks": [],
    }

    with pytest.raises(ValueError, match="as-of"):
        repository.save_source_verification(report, run_id=run_id)


def test_migration_failure_rolls_back_ddl_and_version_registration(tmp_path):
    repository = Tier1Repository(tmp_path / "atomic.db")
    fake_root = tmp_path / "fake-project"
    migration_dir = fake_root / "scripts" / "migrations"
    migration_dir.mkdir(parents=True)
    (migration_dir / "999_broken.sql").write_text(
        """
        CREATE TABLE schema_migrations(
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL,
            description TEXT NOT NULL
        );
        CREATE TABLE must_rollback(id INTEGER PRIMARY KEY);
        THIS IS NOT VALID SQL;
        """,
        encoding="utf-8",
    )
    repository.project_root = fake_root

    with pytest.raises(sqlite3.OperationalError):
        repository._apply_migrations(
            [("999_broken", "999_broken.sql", "failure injection")]
        )

    with repository.connect() as connection:
        assert repository._table_exists(connection, "must_rollback") is False
        assert repository._table_exists(connection, "schema_migrations") is False
