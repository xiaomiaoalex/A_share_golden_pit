"""Typed quality states kept separate from screening business states."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class CapabilityLevel(str, Enum):
    EXACT = "EXACT"
    LIMITED = "LIMITED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


class VerificationStatus(str, Enum):
    PRIMARY_VERIFIED = "PRIMARY_VERIFIED"
    CROSS_VERIFIED = "CROSS_VERIFIED"
    SINGLE_SOURCE = "SINGLE_SOURCE"
    UNVERIFIED = "UNVERIFIED"
    CONFLICT = "CONFLICT"


class QualitySeverity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


SEVERITY_RANK = {
    QualitySeverity.INFO: 0,
    QualitySeverity.LOW: 1,
    QualitySeverity.MEDIUM: 2,
    QualitySeverity.HIGH: 3,
    QualitySeverity.CRITICAL: 4,
}


@dataclass(frozen=True)
class QualityIssue:
    code: str
    severity: QualitySeverity
    message: str
    blocking: bool = False


@dataclass(frozen=True)
class QualityAssessment:
    field_group: str
    provider: str
    capability: CapabilityLevel
    verification_status: VerificationStatus
    issues: tuple[QualityIssue, ...] = field(default_factory=tuple)

    @property
    def blocking(self) -> bool:
        return any(issue.blocking for issue in self.issues)

    @property
    def severity(self) -> QualitySeverity:
        if not self.issues:
            return QualitySeverity.INFO
        return max(
            self.issues, key=lambda issue: SEVERITY_RANK[issue.severity]
        ).severity

    def warning_messages(
        self, minimum: QualitySeverity = QualitySeverity.MEDIUM
    ) -> list[str]:
        threshold = SEVERITY_RANK[minimum]
        return [
            f"[数据质量:{issue.code}] {issue.message}"
            for issue in self.issues
            if SEVERITY_RANK[issue.severity] >= threshold
        ]

    def to_dict(self) -> dict:
        return {
            "field_group": self.field_group,
            "provider": self.provider,
            "capability": self.capability.value,
            "verification_status": self.verification_status.value,
            "severity": self.severity.value,
            "blocking": self.blocking,
            "issues": [
                {
                    **asdict(issue),
                    "severity": issue.severity.value,
                }
                for issue in self.issues
            ],
        }
