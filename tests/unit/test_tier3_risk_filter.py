import json
from pathlib import Path

import pytest

from src.risk.tier3 import RiskModelRegistry, Tier3RiskImporter, Tier3TemplateExporter
from src.screening.tier2_human_ai import Tier2AssessmentImporter
from src.storage.tier2_repository import Tier2Repository
from src.storage.tier3_repository import Tier3Repository
from tests.unit.test_tier2_human_ai import _assessment, _export_one

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _registry():
    return RiskModelRegistry(PROJECT_ROOT / "config" / "tier3_risk_rules.json")


def _stage_b_human_pass(tmp_path):
    tier2 = Tier2Repository(tmp_path / "test.db")
    run_id, _, package = _export_one(tier2, tmp_path)
    source = tmp_path / "tier2-pass.json"
    source.write_text(json.dumps(_assessment(package), ensure_ascii=False), encoding="utf-8")
    imported = Tier2AssessmentImporter(
        tier2, PROJECT_ROOT / "config" / "tier2_ai_schema.json"
    ).import_file(source)
    tier2.save_human_review(
        assessment_id=imported["assessment_ids"][0],
        decision="PASS",
        reviewer="Tier2研究员",
        rationale="逐项核查后确认进入风险过滤",
    )
    return run_id, Tier3Repository(tmp_path / "test.db")


def _classification(symbol="000001", model="INDUSTRIAL"):
    return {
        "symbol": symbol,
        "industry_model": model,
        "industry": "测试行业",
        "rationale": "公司主营业务符合该行业模型定义",
        "sources": [
            {
                "title": "年度报告",
                "publisher": "测试股份",
                "date": "2026-04-01",
                "url_or_document": "annual-report.pdf",
                "page_or_section": "主营业务",
            }
        ],
    }


def _template(tmp_path, model="INDUSTRIAL"):
    run_id, repository = _stage_b_human_pass(tmp_path)
    result = Tier3TemplateExporter(repository, _registry()).export_run(
        run_id, [_classification(model=model)], tmp_path / "tier3"
    )
    path = Path(result["templates"][0]["json_path"])
    return run_id, repository, path, json.loads(path.read_text(encoding="utf-8"))


def _decisive_input(template, *, triggered=None, unknown=None):
    result = json.loads(json.dumps(template, ensure_ascii=False))
    source = {
        "title": "风险核查公告",
        "publisher": "测试股份",
        "date": "2026-05-01",
        "url_or_document": "risk-evidence.pdf",
        "page_or_section": "风险核查",
    }
    for check in result["checks"]:
        if check["check_id"] == unknown:
            continue
        check["status"] = "TRIGGERED" if check["check_id"] == triggered else "CLEAR"
        check["confidence"] = 0.8
        check["facts"] = ["截至筛选日可核查事实"]
        check["counter_evidence"] = ["已检查相反证据"]
        check["sources"] = [source]
        check["reasoning_summary"] = "基于公告形成明确判断"
    return result


def _import(repository, tmp_path, payload, name="tier3-result.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return Tier3RiskImporter(
        repository,
        _registry(),
        PROJECT_ROOT / "config" / "tier3_risk_input_schema.json",
    ).import_file(path)


def test_stage_c_requires_latest_stage_b_human_pass(tmp_path):
    tier2 = Tier2Repository(tmp_path / "test.db")
    run_id, _, _ = _export_one(tier2, tmp_path)
    repository = Tier3Repository(tmp_path / "test.db")

    with pytest.raises(ValueError, match="Stage B人工PASS"):
        repository.tier2_pass_candidates(run_id, ["000001"])


def test_industry_models_have_distinct_business_checks(tmp_path):
    registry = _registry()
    industrial = registry.get("INDUSTRIAL").rule_map
    bank = registry.get("BANK").rule_map
    insurance = registry.get("INSURANCE").rule_map
    real_estate = registry.get("REAL_ESTATE").rule_map

    assert "cfo_profit_persistent_divergence" in industrial
    assert "cfo_profit_persistent_divergence" not in bank
    assert "bank_regulatory_capital_breach" in bank
    assert "insurance_solvency_pressure" in insurance
    assert "realestate_delivery_obligation_stress" in real_estate


def test_template_export_is_bound_to_tier2_review_and_explicit_model(tmp_path):
    run_id, _, path, risk_input = _template(tmp_path, model="BANK")

    assert risk_input["run_id"] == run_id
    assert risk_input["tier2_review_id"]
    assert risk_input["industry_classification"]["industry_model"] == "BANK"
    assert all(check["status"] == "UNKNOWN" for check in risk_input["checks"])
    assert path.exists()


def test_all_clear_can_pass_system_but_still_needs_human_review(tmp_path):
    run_id, repository, _, template = _template(tmp_path)
    result = _import(repository, tmp_path, _decisive_input(template))

    assert result["system_statuses"]["000001"] == "PASS"
    summary = repository.summary(run_id)[0]
    assert summary["system_status"] == "PASS"
    assert summary["human_decision"] is None
    review_id = repository.save_human_review(
        risk_assessment_id=summary["risk_assessment_id"],
        decision="PASS",
        reviewer="首席风险研究员",
        rationale="复核全部行业化风险证据后确认",
    )
    assert review_id
    assert repository.summary(run_id)[0]["human_decision"] == "PASS"


def test_stage_c_cannot_review_after_stage_b_pass_is_superseded(tmp_path):
    run_id, repository, _, template = _template(tmp_path)
    _import(repository, tmp_path, _decisive_input(template))
    assessment = repository.latest_assessment(run_id, "000001")
    tier2 = Tier2Repository(tmp_path / "test.db")
    latest_tier2 = tier2.latest_assessment(run_id, "000001")
    tier2.save_human_review(
        assessment_id=latest_tier2["assessment_id"],
        decision="REJECT",
        reviewer="Tier2研究员",
        rationale="新增反证后撤销Stage B准入",
    )
    assert repository.summary(run_id)[0]["upstream_current"] == 0

    with pytest.raises(ValueError, match="Stage B人工PASS已不是最新"):
        repository.save_human_review(
            risk_assessment_id=assessment["risk_assessment_id"],
            decision="PASS",
            reviewer="风险研究员",
            rationale="不应继续复核陈旧风险评估",
        )


def test_unknown_required_check_forces_review_and_cannot_be_overridden(tmp_path):
    run_id, repository, _, template = _template(tmp_path)
    risk_input = _decisive_input(
        template, unknown="cfo_profit_persistent_divergence"
    )
    imported = _import(repository, tmp_path, risk_input)

    assert imported["system_statuses"]["000001"] == "REVIEW"
    assessment = repository.latest_assessment(run_id, "000001")
    with pytest.raises(ValueError, match="不能覆盖"):
        repository.save_human_review(
            risk_assessment_id=assessment["risk_assessment_id"],
            decision="PASS",
            reviewer="风险研究员",
            rationale="仍存在证据缺口",
        )


def test_hard_veto_always_rejects_and_becomes_value_trap_signal(tmp_path):
    run_id, repository, _, template = _template(tmp_path)
    risk_input = _decisive_input(template, triggered="structural_demand_collapse")
    imported = _import(repository, tmp_path, risk_input)

    assert imported["system_statuses"]["000001"] == "REJECT"
    assessment = repository.latest_assessment(run_id, "000001")
    hard = json.loads(assessment["hard_vetoes_json"])
    traps = json.loads(assessment["value_trap_signals_json"])
    assert hard[0]["check_id"] == "structural_demand_collapse"
    assert traps[0]["check_id"] == "structural_demand_collapse"
    with pytest.raises(ValueError, match="不能覆盖"):
        repository.save_human_review(
            risk_assessment_id=assessment["risk_assessment_id"],
            decision="REVIEW",
            reviewer="风险研究员",
            rationale="不能上调硬否决",
        )


def test_warning_forces_review_without_becoming_hard_veto(tmp_path):
    run_id, repository, _, template = _template(tmp_path)
    risk_input = _decisive_input(
        template, triggered="frequent_auditor_or_finance_head_changes"
    )
    _import(repository, tmp_path, risk_input)
    assessment = repository.latest_assessment(run_id, "000001")

    assert assessment["system_status"] == "REVIEW"
    assert json.loads(assessment["hard_vetoes_json"]) == []
    assert len(json.loads(assessment["risk_warnings_json"])) == 1


def test_model_check_set_cannot_silently_mix_industry_rules(tmp_path):
    _, repository, _, template = _template(tmp_path, model="BANK")
    risk_input = _decisive_input(template)
    risk_input["checks"].append(
        {
            "check_id": "cfo_profit_persistent_divergence",
            "status": "UNKNOWN",
            "confidence": 0,
            "facts": [],
            "inferences": [],
            "counter_evidence": [],
            "sources": [],
            "metrics": [],
            "reasoning_summary": "错误混入工业规则",
        }
    )

    with pytest.raises(ValueError, match="模型不一致"):
        _import(repository, tmp_path, risk_input)


def test_future_source_and_nonfinite_metrics_are_rejected(tmp_path):
    _, repository, _, template = _template(tmp_path)
    future = _decisive_input(template)
    future["checks"][0]["sources"][0]["date"] = "2026-08-11"
    with pytest.raises(ValueError, match="as-of之后"):
        _import(repository, tmp_path, future, "future.json")

    nonfinite = _decisive_input(template)
    nonfinite["checks"][0]["metrics"] = [
        {
            "name": "异常指标",
            "value": float("nan"),
            "unit": "ratio",
            "period": "2026Q1",
            "definition": "测试非法数值",
        }
    ]
    with pytest.raises(ValueError, match="NaN"):
        _import(repository, tmp_path, nonfinite, "nan.json")


def test_batch_import_is_atomic(tmp_path):
    _, repository, _, template = _template(tmp_path)
    good = _decisive_input(template)
    bad = _decisive_input(template)
    bad["tier2_review_id"] = "wrong-review"

    with pytest.raises(ValueError, match="Stage B人工PASS不一致"):
        _import(repository, tmp_path, [good, bad], "batch.json")
    with repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM tier3_risk_inputs").fetchone()[0] == 0


def test_stage_c_rollback_preserves_stage_a_and_b(tmp_path):
    run_id, repository, _, template = _template(tmp_path)
    _import(repository, tmp_path, _decisive_input(template))
    repository.rollback_stage_c()

    with repository.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM tier1_decisions WHERE run_id=?", (run_id,)
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM human_reviews WHERE run_id=?", (run_id,)
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='tier3_risk_assessments'"
        ).fetchone() is None
