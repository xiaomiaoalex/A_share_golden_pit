from datetime import date, timedelta

import pytest

from src.ai_research.contracts import (
    DataEgressClass,
    ModelPolicy,
    ProviderResearchRequest,
    ResearchReportStatus,
)
from src.ai_research.providers import MockAIProvider
from src.ai_research.repository import ResearchRepository
from src.ai_research.service import ResearchService
from src.signals import SignalDirection, SignalRecord, SignalRepository


def test_unified_signals_are_validated_and_aggregated(tmp_path):
    repository = SignalRepository(tmp_path / "signals.db")
    repository.migrate()
    as_of = date(2026, 8, 12)
    signal = SignalRecord(
        signal_id="signal-1",
        run_id="run-1",
        strategy_id="high-dividend",
        release_id="release-1",
        security_id="security-sz-000001",
        symbol="000001",
        as_of_date=as_of,
        direction=SignalDirection.LONG,
        score=82.5,
        rank=1,
        confidence=0.82,
        valid_until=as_of + timedelta(days=5),
        attribution={"dividend_yield": 0.06, "pe_ttm": 8.5},
        data_snapshot_id="snapshot-1",
    )

    repository.save([signal])
    result = repository.aggregate(as_of_date=as_of.isoformat())

    assert result[0]["strategy_id"] == "high-dividend"
    assert result[0]["rank"] == 1
    assert result[0]["attribution"]["dividend_yield"] == 0.06


def test_signal_rejects_missing_attribution():
    with pytest.raises(ValueError, match="候选归因"):
        SignalRecord(
            signal_id="invalid",
            run_id="run",
            strategy_id="strategy",
            release_id="release",
            security_id="security",
            symbol="000001",
            as_of_date=date(2026, 8, 12),
            direction=SignalDirection.LONG,
            score=1.0,
            rank=1,
            confidence=0.5,
            valid_until=date(2026, 8, 12),
            attribution={},
            data_snapshot_id="snapshot",
        )


def _research_fixture(tmp_path):
    repository = ResearchRepository(tmp_path / "research.db")
    repository.migrate()
    repository.create_dataset(
        dataset_id="dataset-1",
        strategy_id="golden-pit",
        release_id="release-1",
        as_of_date="2026-08-12",
        content_hash="a" * 64,
        egress_class=DataEgressClass.DOMESTIC_ALLOWED,
        manifest={"candidate_ids": ["candidate-1"]},
    )
    template_version_id = repository.add_template_version(
        template_id="candidate-evidence",
        version=1,
        prompt="只根据证据生成研究草稿。",
        output_schema={"type": "object"},
        model_policy={"routes": ["mock-cn"]},
        status="PUBLISHED",
    )
    run_id = repository.start_run(
        "dataset-1", template_version_id, "000001 测试股份"
    )
    request = ProviderResearchRequest(
        run_id=run_id,
        dataset_id="dataset-1",
        template_id="candidate-evidence",
        subject="000001 测试股份",
        context={
            "strategy_id": "golden-pit",
            "release_id": "release-1",
            "as_of_date": date(2026, 8, 12),
        },
    )
    report_id = ResearchService(repository).execute(
        request,
        [MockAIProvider()],
        ModelPolicy(policy_id="mock", version=1, routes=("mock-cn",)),
        egress=DataEgressClass.DOMESTIC_ALLOWED,
    )
    return repository, report_id


def test_mock_research_is_append_only_through_review_and_publish(tmp_path):
    repository, report_id = _research_fixture(tmp_path)

    repository.transition(
        report_id, ResearchReportStatus.VALIDATED, actor="validator"
    )
    repository.transition(
        report_id, ResearchReportStatus.IN_REVIEW, actor="reviewer"
    )
    published = repository.transition(
        report_id,
        ResearchReportStatus.PUBLISHED,
        actor="reviewer",
        note="证据完整，批准发布",
    )

    assert published["status"] == "PUBLISHED"
    assert [item["status"] for item in repository.history(report_id)] == [
        "DRAFT",
        "VALIDATED",
        "IN_REVIEW",
        "PUBLISHED",
    ]
    with pytest.raises(ValueError, match="不能从 PUBLISHED"):
        repository.transition(
            report_id, ResearchReportStatus.REJECTED, actor="reviewer"
        )


def test_mock_research_can_be_rejected_without_overwriting_history(tmp_path):
    repository, report_id = _research_fixture(tmp_path)
    repository.transition(
        report_id, ResearchReportStatus.VALIDATED, actor="validator"
    )
    rejected = repository.transition(
        report_id,
        ResearchReportStatus.REJECTED,
        actor="reviewer",
        note="需要补充公告证据",
    )

    assert rejected["status"] == "REJECTED"
    assert len(repository.history(report_id)) == 3


def test_model_policy_blocks_external_and_denied_data():
    capability = MockAIProvider().capabilities()
    policy = ModelPolicy(policy_id="domestic", version=1, routes=("mock-cn",))

    assert (
        policy.select([capability], DataEgressClass.DOMESTIC_ALLOWED).provider_id
        == "mock-cn"
    )
    with pytest.raises(ValueError, match="没有满足"):
        policy.select([capability], DataEgressClass.DENY_AI)

    with pytest.raises(ValueError, match="没有满足"):
        ModelPolicy(
            policy_id="promotion-gated",
            version=1,
            routes=("mock-cn",),
            approved_providers=("another-provider",),
        ).select([capability], DataEgressClass.DOMESTIC_ALLOWED)


def test_cross_strategy_signal_governance_detects_overlap_and_conflict():
    from src.governance import signal_governance

    result = signal_governance(
        [
            {"strategy_id": "a", "security_id": "s1", "symbol": "000001", "direction": "LONG", "score": 80, "confidence": 0.8},
            {"strategy_id": "b", "security_id": "s1", "symbol": "000001", "direction": "SHORT", "score": 70, "confidence": 0.7},
            {"strategy_id": "b", "security_id": "s2", "symbol": "000002", "direction": "LONG", "score": 60, "confidence": 0.6},
        ]
    )

    assert result["overlaps"][0]["jaccard"] == 0.5
    assert result["conflicts"][0]["symbol"] == "000001"
