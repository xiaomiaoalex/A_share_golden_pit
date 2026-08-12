from datetime import date

from src.ai_research import (
    EvidenceReference,
    ResearchFinding,
    ResearchReport,
    ResearchVerdict,
)
from src.ai_research.evaluation import (
    PromotionThresholds,
    ResearchGrader,
)
from src.artifacts import ArtifactRepository


def _report():
    return ResearchReport(
        subject="000001",
        strategy_id="golden-pit",
        release_id="release-1",
        as_of_date=date(2026, 8, 12),
        thesis="证据研究",
        verdict=ResearchVerdict.NEUTRAL,
        confidence=0.7,
        findings=(ResearchFinding("finding", "利润为100", ("evidence",)),),
        evidence=(EvidenceReference("evidence", "item", "年报", "p10", "a" * 64),),
        counter_evidence=(),
        risks=(),
        assumptions=(),
        data_gaps=(),
        falsification_conditions=("利润更正",),
        recommended_actions=("人工复核",),
    )


def test_model_promotion_requires_citations_numbers_and_point_in_time(tmp_path):
    grader = ResearchGrader()
    passing = grader.grade(
        _report(),
        evidence_support={"evidence": True},
        numeric_claims=[(100.0, 100.0)],
        evidence_dates=[date(2026, 3, 20)],
        latency_ms=1000,
        cost=0.1,
    )
    failing = grader.grade(
        _report(),
        evidence_support={"evidence": False},
        numeric_claims=[(101.0, 100.0)],
        evidence_dates=[date(2026, 8, 13)],
        latency_ms=1000,
        cost=0.1,
    )

    assert grader.promotable(passing, PromotionThresholds()) == (True, ())
    promoted, reasons = grader.promotable(failing, PromotionThresholds())
    assert not promoted
    assert set(reasons) == {"CITATION_SUPPORT", "NUMERIC_ACCURACY", "POINT_IN_TIME_VIOLATION"}

    artifacts = ArtifactRepository(tmp_path / "evaluation.db")
    artifacts.migrate()
    artifact = artifacts.append(
        artifact_id="eval:qwen:candidate-evidence:v1",
        artifact_type="EVALUATION",
        status="PROMOTABLE",
        payload=grader.as_payload(passing),
        created_by="local-grader",
    )
    assert artifact["payload"]["numeric_accuracy"] == 1.0
