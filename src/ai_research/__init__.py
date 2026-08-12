"""Governed AI-assisted research domain."""

from .contracts import (
    AIProviderPort,
    DataEgressClass,
    EvidenceReference,
    ModelCapability,
    ModelPolicy,
    ProviderResearchRequest,
    ProviderResearchResult,
    ResearchDataset,
    ResearchFinding,
    ResearchReport,
    ResearchReportStatus,
    ResearchRun,
    ResearchTemplate,
    ResearchVerdict,
)
from .repository import ResearchRepository
from .service import ResearchService

__all__ = [
    "AIProviderPort",
    "DataEgressClass",
    "EvidenceReference",
    "ModelCapability",
    "ModelPolicy",
    "ProviderResearchRequest",
    "ProviderResearchResult",
    "ResearchDataset",
    "ResearchFinding",
    "ResearchReport",
    "ResearchReportStatus",
    "ResearchRepository",
    "ResearchRun",
    "ResearchService",
    "ResearchTemplate",
    "ResearchVerdict",
]
