import json

import pytest

from src.ai_research import DataEgressClass, ResearchRepository
from src.data.point_in_time import PointInTimeRepository
from src.data.snapshots import SnapshotService


def test_security_identity_and_financial_revisions_are_point_in_time(tmp_path):
    repository = PointInTimeRepository(tmp_path / "pit.db")
    repository.migrate()
    repository.add_security(
        security_id="security-1",
        issuer_name="示例公司",
        symbol="000001",
        exchange="SZ",
        valid_from="2020-01-01",
        listed_at="2020-01-01",
    )
    repository.change_code(
        "security-1",
        symbol="001001",
        exchange="SZ",
        name="示例股份",
        valid_from="2025-01-01",
    )
    repository.add_financial_report(
        security_id="security-1",
        report_period="2024-12-31",
        announcement_date="2025-03-20",
        payload={"revenue": 100},
        source_record_id="source-1",
    )
    repository.add_financial_report(
        security_id="security-1",
        report_period="2024-12-31",
        announcement_date="2025-05-01",
        payload={"revenue": 98, "revision_reason": "更正"},
        source_record_id="source-2",
    )

    assert repository.security_as_of("security-1", "2024-08-01")["symbol"] == "000001"
    assert repository.security_as_of("security-1", "2026-08-01")["symbol"] == "001001"
    assert repository.financial_reports_as_of("security-1", "2025-04-01")[0]["payload"]["revenue"] == 100
    latest = repository.financial_reports_as_of("security-1", "2025-06-01")[0]
    assert latest["revision"] == 2
    assert latest["payload"]["revenue"] == 98


def test_snapshot_is_reproducible_queryable_and_ai_egress_is_enforced(tmp_path):
    db_path = tmp_path / "snapshots.db"
    service = SnapshotService(db_path, tmp_path / "parquet")
    service.migrate()
    rows = [
        {"security_id": "security-2", "score": 70.0, "internal_note": "secret"},
        {"security_id": "security-1", "score": 80.0, "internal_note": "private"},
    ]
    first = service.publish(
        dataset_type="strategy-signals",
        as_of_date="2026-08-12",
        rows=rows,
        lineage={"run_id": "run-1", "source": "strategy_signals"},
        quality={"coverage": 1.0, "missing_rate": 0.0},
    )
    second = service.publish(
        dataset_type="strategy-signals",
        as_of_date="2026-08-12",
        rows=list(reversed(rows)),
        lineage={"run_id": "run-1", "source": "strategy_signals"},
        quality={"coverage": 1.0, "missing_rate": 0.0},
    )

    assert first["content_hash"] == second["content_hash"]
    assert service.query(first["snapshot_id"], fields=["security_id", "score"], limit=10)[0]["security_id"] == "security-1"
    with pytest.raises(ValueError, match="白名单"):
        service.query(first["snapshot_id"], fields=["missing_field"])

    service.set_egress_policy("security_id", DataEgressClass.DOMESTIC_ALLOWED)
    service.set_egress_policy("score", DataEgressClass.DOMESTIC_ALLOWED)
    service.set_egress_policy("internal_note", DataEgressClass.LOCAL_ONLY)
    service.publish_ai_dataset(
        dataset_id="ai-dataset-1",
        snapshot_id=first["snapshot_id"],
        strategy_id="golden-pit",
        release_id="release-1",
        fields=["security_id", "score"],
    )
    overview = ResearchRepository(db_path).overview()
    assert json.loads(
        next(
            row[0]
            for row in __import__("sqlite3").connect(db_path).execute(
                "SELECT manifest_json FROM research_datasets WHERE dataset_id='ai-dataset-1'"
            )
        )
    )["fields"] == ["security_id", "score"]
    assert overview["datasets"][0]["egress_class"] == "DOMESTIC_ALLOWED"
    with pytest.raises(ValueError, match="外发策略阻断"):
        service.publish_ai_dataset(
            dataset_id="ai-dataset-blocked",
            snapshot_id=first["snapshot_id"],
            strategy_id="golden-pit",
            release_id="release-1",
            fields=["internal_note"],
        )
    service.set_egress_policy(
        "internal_note", DataEgressClass.MASK_BEFORE_SEND, "HASH"
    )
    with pytest.raises(ValueError, match="外发策略阻断"):
        service.publish_ai_dataset(
            dataset_id="ai-dataset-unmasked",
            snapshot_id=first["snapshot_id"],
            strategy_id="golden-pit",
            release_id="release-1",
            fields=["internal_note"],
        )
