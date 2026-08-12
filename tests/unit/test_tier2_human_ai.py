import hashlib
import json
import sqlite3
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from config.tier1 import Tier1Config
from main import _formal_workflow_command
from src.screening.tier1_v2.decision import evaluate_tier1
from src.screening.tier2_human_ai import (
    Tier2AssessmentImporter,
    Tier2EvidenceExporter,
)
from src.screening.tier2_human_ai.constants import DIMENSIONS, SCENARIOS
from src.storage.tier2_repository import Tier2Repository
from src.strategies.golden_pit.resources import EVIDENCE_SCHEMA
from tests.unit.test_tier1_decision import decision_input


def _finished_pass_run(repository: Tier2Repository) -> str:
    run_id = repository.tier1.begin_run(date(2026, 8, 10), Tier1Config())
    decision = evaluate_tier1(decision_input())
    repository.tier1.save_decision(run_id, decision)
    repository.tier1.finish_run(
        run_id, status="FINISHED", universe_size=1, price_dates=[date(2026, 8, 8)]
    )
    return run_id


def _export_one(repository: Tier2Repository, tmp_path):
    run_id = _finished_pass_run(repository)
    result = Tier2EvidenceExporter(repository).export_run(
        run_id, tmp_path / "packages"
    )
    package = repository.package(result["packages"][0]["package_id"])
    return run_id, result, package


def _assessment(package, verdict="PASS"):
    claim = "可核查事实"
    snapshot = Path(package["json_path"]).resolve()
    source = {
        "title": "定期报告",
        "publisher": "测试公司",
        "date": "2026-04-01",
        "available_at": "2026-04-01T18:00:00+08:00",
        "url_or_document": "evidence-package.json",
        "page_or_section": "财务报表",
        "snapshot_path": str(snapshot),
        "content_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        "evidence_excerpt": '"screen_status": "PASS"',
        "supported_claims": [claim],
    }
    return {
        "schema_version": "tier2-ai-v1.1",
        "run_id": package["run_id"],
        "symbol": package["symbol"],
        "as_of_date": package["as_of_date"],
        "evidence_package_id": package["package_id"],
        "evidence_content_hash": package["content_hash"],
        "ai_provider": "manual",
        "ai_model": None,
        "recommendation": "PASS",
        "dimensions": [
            {
                "dimension": dimension,
                "verdict": verdict,
                "confidence": 0.8,
                "facts": [] if verdict == "INSUFFICIENT_EVIDENCE" else [claim],
                "inferences": [],
                "counter_evidence": [] if verdict == "INSUFFICIENT_EVIDENCE" else ["待证伪的反方观点"],
                "sources": [] if verdict == "INSUFFICIENT_EVIDENCE" else [dict(source)],
                "reasoning_summary": "证据不足" if verdict == "INSUFFICIENT_EVIDENCE" else "有证据支持",
                "falsification_conditions": ["指标持续恶化"],
            }
            for dimension in DIMENSIONS
        ],
        "scenario_analysis": [
            {
                "scenario": scenario,
                "assumptions": ["测试假设"],
                "value_per_share": 10.0,
                "annualized_return_3y": 0.1,
                "annualized_return_5y": 0.08,
                "permanent_loss_risk": "MEDIUM",
            }
            for scenario in SCENARIOS
        ],
        "overall_reasoning": "测试结论",
        "overall_counter_evidence": ["反方证据"],
        "falsification_conditions": ["条件1", "条件2", "条件3"],
    }


def _importer(repository):
    return Tier2AssessmentImporter(repository, EVIDENCE_SCHEMA)


def test_export_only_tier1_pass_and_marks_missing_evidence(tmp_path):
    repository = Tier2Repository(tmp_path / "test.db")
    run_id, result, package = _export_one(repository, tmp_path)

    assert result["package_count"] == 1
    assert package["run_id"] == run_id
    assert package["coverage_status"] == "PARTIAL"
    missing = json.loads(package["missing_sections_json"])
    assert "cash_flow_and_capex" in missing
    assert (tmp_path / "packages" / "index.json").exists()
    assert (tmp_path / "packages" / "tier2_ai_schema.json").exists()


def test_explicit_non_pass_symbol_is_not_silently_omitted(tmp_path):
    repository = Tier2Repository(tmp_path / "test.db")
    run_id = _finished_pass_run(repository)

    with pytest.raises(ValueError, match="不在.*PASS"):
        Tier2EvidenceExporter(repository).export_run(
            run_id, tmp_path / "packages", symbols=["600000"]
        )


def test_formal_workflow_reports_the_next_controlled_step(tmp_path, capsys):
    repository = Tier2Repository(tmp_path / "test.db")
    run_id = _finished_pass_run(repository)

    _formal_workflow_command(
        SimpleNamespace(as_of=None, run_id=run_id, db=str(tmp_path / "test.db"))
    )

    output = json.loads(capsys.readouterr().out)
    assert output["stage_a"]["pass_count"] == 1
    assert "export-tier2" in output["next_action"]


def test_invalid_ai_schema_is_rejected_without_database_write(tmp_path):
    repository = Tier2Repository(tmp_path / "test.db")
    _, _, package = _export_one(repository, tmp_path)
    assessment = _assessment(package)
    del assessment["dimensions"]
    source = tmp_path / "bad.json"
    source.write_text(json.dumps(assessment, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="JSON Schema"):
        _importer(repository).import_file(source)
    with repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM ai_assessments").fetchone()[0] == 0


def test_batch_import_is_atomic_when_one_result_is_invalid(tmp_path):
    repository = Tier2Repository(tmp_path / "test.db")
    _, _, package = _export_one(repository, tmp_path)
    good = _assessment(package)
    bad = _assessment(package)
    bad["evidence_content_hash"] = "0" * 64
    source = tmp_path / "batch.json"
    source.write_text(json.dumps([good, bad], ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="证据包不一致"):
        _importer(repository).import_file(source)
    with repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM ai_assessments").fetchone()[0] == 0


def test_ai_source_after_as_of_is_rejected(tmp_path):
    repository = Tier2Repository(tmp_path / "test.db")
    _, _, package = _export_one(repository, tmp_path)
    assessment = _assessment(package)
    assessment["dimensions"][0]["sources"][0]["date"] = "2026-08-11"
    source = tmp_path / "future-source.json"
    source.write_text(json.dumps(assessment, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="as-of之后"):
        _importer(repository).import_file(source)


def test_ai_source_snapshot_hash_and_excerpt_are_verified(tmp_path):
    repository = Tier2Repository(tmp_path / "test.db")
    _, _, package = _export_one(repository, tmp_path)

    bad_hash = _assessment(package)
    bad_hash["dimensions"][0]["sources"][0]["content_sha256"] = "0" * 64
    source = tmp_path / "bad-hash.json"
    source.write_text(json.dumps(bad_hash, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256不一致"):
        _importer(repository).import_file(source)

    bad_excerpt = _assessment(package)
    bad_excerpt["dimensions"][0]["sources"][0]["evidence_excerpt"] = "不存在的摘录"
    source = tmp_path / "bad-excerpt.json"
    source.write_text(json.dumps(bad_excerpt, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="摘录未在快照文本中找到"):
        _importer(repository).import_file(source)


def test_ai_fact_must_be_bound_to_verified_source(tmp_path):
    repository = Tier2Repository(tmp_path / "test.db")
    _, _, package = _export_one(repository, tmp_path)
    assessment = _assessment(package)
    assessment["dimensions"][0]["facts"].append("未绑定事实")
    source = tmp_path / "unbound-fact.json"
    source.write_text(json.dumps(assessment, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="未绑定到可验证来源"):
        _importer(repository).import_file(source)


def test_ai_result_bound_to_superseded_evidence_is_rejected(tmp_path):
    repository = Tier2Repository(tmp_path / "test.db")
    _, _, old_package = _export_one(repository, tmp_path)
    assessment = _assessment(old_package)
    newer_created_at = (
        datetime.fromisoformat(old_package["created_at"]) + timedelta(seconds=1)
    ).isoformat(timespec="seconds")
    newer = {
        "package_id": str(uuid.uuid4()),
        "run_id": old_package["run_id"],
        "symbol": old_package["symbol"],
        "stock_name": old_package["stock_name"],
        "as_of_date": old_package["as_of_date"],
        "package_version": old_package["package_version"],
        "content_hash": "f" * 64,
        "coverage_status": "PARTIAL",
        "missing_sections": ["cash_flow_and_capex"],
        "evidence": {"updated": True},
        "created_at": newer_created_at,
    }
    repository.save_evidence_package(newer)
    source = tmp_path / "stale.json"
    source.write_text(json.dumps(assessment, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="更新版本替代"):
        _importer(repository).import_file(source)


def test_export_rejects_future_dated_stage_a_evidence(tmp_path):
    repository = Tier2Repository(tmp_path / "test.db")
    run_id = _finished_pass_run(repository)
    with repository.connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO source_observations(
                run_id, symbol, field_group, provider, endpoint, request_json,
                fetch_status, fetched_at, available_at, row_count,
                quality_warnings_json
            ) VALUES (?, '000001', 'financial_statements', 'TEST', 'test', '{}',
                      'SUCCESS', '2026-08-10', '2026-08-11', 1, '[]')
            """,
            (run_id,),
        )
        observation_id = cursor.lastrowid
        connection.execute(
            """
            INSERT INTO tier1_raw_metrics(
                run_id, symbol, metric_name, report_period, period_type,
                raw_value, unit, announcement_date, available_at,
                source_observation_id
            ) VALUES (?, '000001', 'operating_revenue', '2026-06-30',
                      'CUMULATIVE_REPORTED', 1, 'CNY', '2026-08-11',
                      '2026-08-11', ?)
            """,
            (run_id, observation_id),
        )

    with pytest.raises(ValueError, match="as-of之后"):
        Tier2EvidenceExporter(repository).export_run(run_id, tmp_path / "packages")


def test_insufficient_evidence_can_only_enter_review(tmp_path):
    repository = Tier2Repository(tmp_path / "test.db")
    run_id, _, package = _export_one(repository, tmp_path)
    assessment = _assessment(package, verdict="INSUFFICIENT_EVIDENCE")
    source = tmp_path / "insufficient.json"
    source.write_text(json.dumps(assessment, ensure_ascii=False), encoding="utf-8")

    imported = _importer(repository).import_file(source)

    assert imported["system_recommendations"]["000001"] == "REVIEW"
    latest = repository.latest_assessment(run_id, "000001")
    with pytest.raises(ValueError, match="不能覆盖"):
        repository.save_human_review(
            assessment_id=latest["assessment_id"],
            decision="PASS",
            reviewer="研究员",
            rationale="证据仍不足",
        )


def test_dimension_fail_is_a_veto_and_human_cannot_override(tmp_path):
    repository = Tier2Repository(tmp_path / "test.db")
    run_id, _, package = _export_one(repository, tmp_path)
    assessment = _assessment(package)
    assessment["dimensions"][0]["verdict"] = "FAIL"
    source = tmp_path / "fail.json"
    source.write_text(json.dumps(assessment, ensure_ascii=False), encoding="utf-8")

    _importer(repository).import_file(source)
    latest = repository.latest_assessment(run_id, "000001")
    assert latest["system_recommendation"] == "REJECT"
    with pytest.raises(ValueError, match="不能覆盖"):
        repository.save_human_review(
            assessment_id=latest["assessment_id"],
            decision="PASS",
            reviewer="研究员",
            rationale="不能覆盖否决",
        )


def test_system_pass_still_requires_append_only_human_confirmation(tmp_path):
    repository = Tier2Repository(tmp_path / "test.db")
    run_id, _, package = _export_one(repository, tmp_path)
    source = tmp_path / "pass.json"
    source.write_text(json.dumps(_assessment(package), ensure_ascii=False), encoding="utf-8")
    _importer(repository).import_file(source)
    latest = repository.latest_assessment(run_id, "000001")

    before = repository.review_summary(run_id)[0]
    assert before["human_decision"] is None
    review_id = repository.save_human_review(
        assessment_id=latest["assessment_id"],
        decision="PASS",
        reviewer="首席研究员",
        rationale="逐项复核证据与反证后确认",
    )
    after = repository.review_summary(run_id)[0]
    assert review_id
    assert after["human_decision"] == "PASS"


def test_stage_b_rollback_preserves_stage_a_tables_and_rows(tmp_path):
    repository = Tier2Repository(tmp_path / "test.db")
    run_id = _finished_pass_run(repository)
    repository.rollback_stage_b()

    with repository.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM tier1_decisions WHERE run_id=?", (run_id,)
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='tier2_evidence_packages'"
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='tier3_risk_assessments'"
        ).fetchone() is None


def test_stage_b_migration_is_additive_to_legacy_database(tmp_path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE legacy_table(id INTEGER PRIMARY KEY)")
    repository = Tier2Repository(db_path)
    repository.migrate()

    with repository.connect() as connection:
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='legacy_table'"
        ).fetchone()
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='human_reviews'"
        ).fetchone()
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='tier3_risk_assessments'"
        ).fetchone() is None
