import sqlite3
from datetime import date

from config.tier1 import Tier1Config
from src.storage.tier1_repository import Tier1Repository
from src.screening.tier1_v2.decision import evaluate_tier1
from tests.unit.test_tier1_decision import decision_input


def test_additive_migration_and_rollback_preserve_legacy_table(tmp_path):
    db_path = tmp_path / "test.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE legacy_table(id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO legacy_table(value) VALUES ('keep')")

    repository = Tier1Repository(db_path)
    repository.migrate()
    with repository.connect() as connection:
        assert connection.execute(
            "SELECT value FROM legacy_table"
        ).fetchone()[0] == "keep"
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='tier1_decisions'"
        ).fetchone()

    repository.rollback_stage_a()
    with repository.connect() as connection:
        assert connection.execute(
            "SELECT value FROM legacy_table"
        ).fetchone()[0] == "keep"
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='tier1_decisions'"
        ).fetchone() is None


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
