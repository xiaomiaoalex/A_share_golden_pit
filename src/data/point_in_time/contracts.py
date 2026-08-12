"""Data acquisition contracts that preserve quality state and lineage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Generic, Optional, TypeVar

from .models import CorporateAction, DividendEvent

T = TypeVar("T")


class FetchStatus(str, Enum):
    SUCCESS = "SUCCESS"
    EMPTY = "EMPTY"
    ERROR = "ERROR"
    SCHEMA_ERROR = "SCHEMA_ERROR"


@dataclass
class DataEnvelope(Generic[T]):
    status: FetchStatus
    data: Optional[T]
    provider: str
    endpoint: str
    request: dict[str, Any]
    fetched_at: datetime = field(default_factory=datetime.now)
    available_at: Optional[date] = None
    row_count: Optional[int] = None
    schema_hash: Optional[str] = None
    payload_hash: Optional[str] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    quality_warnings: list[str] = field(default_factory=list)
    raw_payload: Optional[Any] = None
    observation_id: Optional[int] = None

    @property
    def usable(self) -> bool:
        return self.status == FetchStatus.SUCCESS and self.data is not None


@dataclass(frozen=True)
class UniverseItem:
    symbol: str
    name: str
    exchange: str


@dataclass(frozen=True)
class DividendBundle:
    events: tuple[DividendEvent, ...]
    actions: tuple[CorporateAction, ...]
