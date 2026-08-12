"""Supplier-neutral report grading and model promotion gates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Iterable, Mapping

from src.ai_research.contracts import ResearchReport


@dataclass(frozen=True)
class EvaluationMetrics:
    schema_compliant: bool
    citation_presence: float
    citation_support: float
    numeric_accuracy: float
    point_in_time_violations: int
    latency_ms: int
    cost: float


@dataclass(frozen=True)
class PromotionThresholds:
    min_citation_presence: float = 1.0
    min_citation_support: float = 0.9
    min_numeric_accuracy: float = 1.0
    max_point_in_time_violations: int = 0
    max_cost: float = 10.0


class ResearchGrader:
    def grade(
        self,
        report: ResearchReport,
        *,
        evidence_support: Mapping[str, bool],
        numeric_claims: Iterable[tuple[float, float]],
        evidence_dates: Iterable[date],
        latency_ms: int,
        cost: float,
    ) -> EvaluationMetrics:
        try:
            report.validate()
            schema_compliant = True
        except ValueError:
            schema_compliant = False
        major = [item for item in report.findings if item.is_major]
        cited = [item for item in major if item.evidence_ids]
        cited_ids = [evidence_id for item in major for evidence_id in item.evidence_ids]
        supported = sum(bool(evidence_support.get(item)) for item in cited_ids)
        comparisons = list(numeric_claims)
        accurate = sum(abs(claim - fact) <= max(1e-9, abs(fact) * 1e-9) for claim, fact in comparisons)
        return EvaluationMetrics(
            schema_compliant=schema_compliant,
            citation_presence=len(cited) / len(major) if major else 1.0,
            citation_support=supported / len(cited_ids) if cited_ids else 1.0,
            numeric_accuracy=accurate / len(comparisons) if comparisons else 1.0,
            point_in_time_violations=sum(item > report.as_of_date for item in evidence_dates),
            latency_ms=latency_ms,
            cost=cost,
        )

    @staticmethod
    def promotable(
        metrics: EvaluationMetrics, thresholds: PromotionThresholds
    ) -> tuple[bool, tuple[str, ...]]:
        failures = []
        if not metrics.schema_compliant:
            failures.append("SCHEMA_NONCOMPLIANT")
        if metrics.citation_presence < thresholds.min_citation_presence:
            failures.append("CITATION_PRESENCE")
        if metrics.citation_support < thresholds.min_citation_support:
            failures.append("CITATION_SUPPORT")
        if metrics.numeric_accuracy < thresholds.min_numeric_accuracy:
            failures.append("NUMERIC_ACCURACY")
        if metrics.point_in_time_violations > thresholds.max_point_in_time_violations:
            failures.append("POINT_IN_TIME_VIOLATION")
        if metrics.cost > thresholds.max_cost:
            failures.append("COST")
        return not failures, tuple(failures)

    @staticmethod
    def as_payload(metrics: EvaluationMetrics) -> dict:
        return asdict(metrics)
