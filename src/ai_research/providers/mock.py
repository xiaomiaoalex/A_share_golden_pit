"""Deterministic provider used for contract and governance acceptance tests."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..contracts import (
    EvidenceReference,
    ModelCapability,
    ProviderResearchRequest,
    ProviderResearchResult,
    ResearchFinding,
    ResearchReport,
    ResearchVerdict,
)


class MockAIProvider:
    def capabilities(self) -> ModelCapability:
        return ModelCapability(
            provider_id="mock-cn",
            model_id="mock-research-v1",
            region="CN",
            tool_calling=True,
            structured_output=True,
            context_tokens=16_384,
            adapter_version="1.0",
        )

    def health_check(self) -> Mapping[str, Any]:
        return {"status": "ok", "provider_id": "mock-cn"}

    def run_research(
        self,
        request: ProviderResearchRequest,
        tools: Sequence[Mapping[str, Any]],
        output_schema: Mapping[str, Any],
    ) -> ProviderResearchResult:
        evidence = EvidenceReference(
            evidence_id="evidence-1",
            dataset_item_id="candidate-1",
            title="模拟候选确定性记录",
            locator=f"dataset:{request.dataset_id}/candidate-1",
            content_hash="0" * 64,
        )
        report = ResearchReport(
            subject=request.subject,
            strategy_id=str(request.context["strategy_id"]),
            release_id=str(request.context["release_id"]),
            as_of_date=request.context["as_of_date"],
            thesis="现有证据支持进入人工复核，不改变原量化结论。",
            verdict=ResearchVerdict.NEUTRAL,
            confidence=0.7,
            findings=(
                ResearchFinding(
                    finding_id="finding-1",
                    claim="候选记录存在且可追溯。",
                    evidence_ids=(evidence.evidence_id,),
                ),
            ),
            evidence=(evidence,),
            counter_evidence=("模拟 Provider 不提供外部增量事实。",),
            risks=("仍需人工核查真实公告。",),
            assumptions=("输入数据集已通过平台质量校验。",),
            data_gaps=("缺少外部公告正文。",),
            falsification_conditions=("确定性候选记录被质量审计否定。",),
            recommended_actions=("提交人工审核。",),
        )
        return ProviderResearchResult(
            report=report,
            provider_id="mock-cn",
            model_id="mock-research-v1",
            request_id=f"mock-{request.run_id}",
            input_tokens=100,
            output_tokens=200,
            cost=0.0,
        )
