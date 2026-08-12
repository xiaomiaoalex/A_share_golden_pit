from src.ai_research import DataEgressClass, ResearchRepository
from src.ai_research.retrieval import EvidenceIndex


def _embedding(text: str):
    return [float(text.count("现金流")), float(text.count("利润")), 1.0]


def test_evidence_search_is_dataset_scoped_hybrid_and_egress_controlled(tmp_path):
    db_path = tmp_path / "evidence.db"
    repository = ResearchRepository(db_path)
    repository.migrate()
    for dataset_id in ("dataset-a", "dataset-b"):
        repository.create_dataset(
            dataset_id=dataset_id,
            strategy_id="golden-pit",
            release_id="release-1",
            as_of_date="2026-08-12",
            content_hash=("a" if dataset_id.endswith("a") else "b") * 64,
            egress_class=DataEgressClass.DOMESTIC_ALLOWED,
            manifest={},
        )
    index = EvidenceIndex(db_path, _embedding)
    index.add_document(
        dataset_id="dataset-a",
        title="年度报告",
        publisher="测试股份",
        published_at="2026-03-20",
        source_uri="source://annual-report",
        content="经营现金流持续改善，利润质量得到支持。" * 30,
        egress_class=DataEgressClass.DOMESTIC_ALLOWED,
    )
    index.add_document(
        dataset_id="dataset-a",
        title="内部备忘",
        publisher="内部",
        published_at="2026-03-21",
        source_uri="source://private",
        content="现金流内部敏感分析。" * 30,
        egress_class=DataEgressClass.LOCAL_ONLY,
    )
    index.add_document(
        dataset_id="dataset-b",
        title="其他报告",
        publisher="其他公司",
        published_at="2026-03-20",
        source_uri="source://other",
        content="现金流内容属于另一个数据集。" * 30,
        egress_class=DataEgressClass.DOMESTIC_ALLOWED,
    )

    results = index.search("dataset-a", "现金流", limit=5)

    assert results
    assert {item["title"] for item in results} == {"年度报告"}
    assert all(item["vector_score"] is not None for item in results)
    assert all(len(item["content_hash"]) == 64 for item in results)


def test_external_region_requires_explicit_external_policy(tmp_path):
    db_path = tmp_path / "external.db"
    repository = ResearchRepository(db_path)
    repository.migrate()
    repository.create_dataset(
        dataset_id="dataset",
        strategy_id="golden-pit",
        release_id="release",
        as_of_date="2026-08-12",
        content_hash="c" * 64,
        egress_class=DataEgressClass.DOMESTIC_ALLOWED,
        manifest={},
    )
    index = EvidenceIndex(db_path)
    index.add_document(
        dataset_id="dataset",
        title="公告",
        publisher="公司",
        published_at="2026-01-01",
        source_uri="source://notice",
        content="利润公告内容。" * 50,
        egress_class=DataEgressClass.DOMESTIC_ALLOWED,
    )

    assert index.search("dataset", "利润", target_region="EXTERNAL") == []
