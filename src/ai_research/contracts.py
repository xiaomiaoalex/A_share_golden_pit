"""Supplier-independent contracts for governed AI research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any, Mapping, Protocol, Sequence


class DataEgressClass(StrEnum):
    DOMESTIC_ALLOWED = "DOMESTIC_ALLOWED"
    APPROVED_EXTERNAL = "APPROVED_EXTERNAL"
    MASK_BEFORE_SEND = "MASK_BEFORE_SEND"
    LOCAL_ONLY = "LOCAL_ONLY"
    DENY_AI = "DENY_AI"


class ResearchReportStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    IN_REVIEW = "IN_REVIEW"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"


class ResearchVerdict(StrEnum):
    SUPPORTIVE = "SUPPORTIVE"
    NEUTRAL = "NEUTRAL"
    CONTRADICTORY = "CONTRADICTORY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class ResearchDataset:
    dataset_id: str
    strategy_id: str
    release_id: str
    as_of_date: date
    content_hash: str
    egress_class: DataEgressClass
    manifest: Mapping[str, Any]
    status: str = "READY"


@dataclass(frozen=True)
class ResearchTemplate:
    template_id: str
    version: int
    prompt: str
    output_schema: Mapping[str, Any]
    model_policy: "ModelPolicy"
    status: str = "DRAFT"


@dataclass(frozen=True)
class ResearchRun:
    run_id: str
    dataset_id: str
    template_version_id: str
    subject: str
    status: str = "RUNNING"


@dataclass(frozen=True)
class ModelCapability:
    provider_id: str
    model_id: str
    region: str
    tool_calling: bool
    structured_output: bool
    context_tokens: int
    adapter_version: str


@dataclass(frozen=True)
class ModelPolicy:
    policy_id: str
    version: int
    routes: tuple[str, ...] = ("deepseek", "qwen")
    allow_external: bool = False
    require_structured_output: bool = True
    require_tool_calling: bool = True
    approved_providers: tuple[str, ...] = ()

    def select(
        self,
        capabilities: Sequence[ModelCapability],
        egress: DataEgressClass,
    ) -> ModelCapability:
        available = {item.provider_id: item for item in capabilities}
        for provider_id in self.routes:
            if self.approved_providers and provider_id not in self.approved_providers:
                continue
            item = available.get(provider_id)
            if item is None:
                continue
            if not self.allow_external and item.region != "CN":
                continue
            if egress in {DataEgressClass.LOCAL_ONLY, DataEgressClass.DENY_AI}:
                continue
            if self.require_structured_output and not item.structured_output:
                continue
            if self.require_tool_calling and not item.tool_calling:
                continue
            return item
        raise ValueError("没有满足能力和数据出境政策的模型")


@dataclass(frozen=True)
class EvidenceReference:
    evidence_id: str
    dataset_item_id: str
    title: str
    locator: str
    content_hash: str


@dataclass(frozen=True)
class ResearchFinding:
    finding_id: str
    claim: str
    evidence_ids: tuple[str, ...]
    is_major: bool = True


@dataclass(frozen=True)
class ResearchReport:
    subject: str
    strategy_id: str
    release_id: str
    as_of_date: date
    thesis: str
    verdict: ResearchVerdict
    confidence: float
    findings: tuple[ResearchFinding, ...]
    evidence: tuple[EvidenceReference, ...]
    counter_evidence: tuple[str, ...]
    risks: tuple[str, ...]
    assumptions: tuple[str, ...]
    data_gaps: tuple[str, ...]
    falsification_conditions: tuple[str, ...]
    recommended_actions: tuple[str, ...]
    schema_version: str = "research-report-v1"

    def validate(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("研究报告置信度必须在 0 到 1 之间")
        evidence_ids = {item.evidence_id for item in self.evidence}
        missing = {
            evidence_id
            for finding in self.findings
            if finding.is_major
            for evidence_id in finding.evidence_ids
            if evidence_id not in evidence_ids
        }
        if any(item.is_major and not item.evidence_ids for item in self.findings):
            raise ValueError("重大结论必须包含证据引用")
        if missing:
            raise ValueError(f"研究报告引用不存在: {sorted(missing)}")


@dataclass(frozen=True)
class ProviderResearchRequest:
    run_id: str
    dataset_id: str
    template_id: str
    subject: str
    context: Mapping[str, Any]


@dataclass(frozen=True)
class ProviderResearchResult:
    report: ResearchReport
    provider_id: str
    model_id: str
    request_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0


class AIProviderPort(Protocol):
    def capabilities(self) -> ModelCapability: ...
    def health_check(self) -> Mapping[str, Any]: ...
    def run_research(
        self,
        request: ProviderResearchRequest,
        tools: Sequence[Mapping[str, Any]],
        output_schema: Mapping[str, Any],
    ) -> ProviderResearchResult: ...
