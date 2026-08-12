"""Stable contracts between strategy modules and the application shell."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from http import HTTPStatus
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class StrategyDescriptor:
    """Metadata used by the strategy catalog and frontend module loader."""

    strategy_id: str
    name: str
    short_name: str
    description: str
    version: str
    ui_module: str
    status: Literal["ACTIVE", "BETA", "PAUSED"] = "ACTIVE"
    stages: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    accent: str = "emerald"

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["id"] = value.pop("strategy_id")
        return value


@dataclass(frozen=True)
class StrategyOperation:
    """A strategy-owned operation returned to the generic HTTP executor."""

    kind: Literal["job", "result"]
    status: HTTPStatus
    label: str = ""
    command: tuple[str, ...] = ()
    payload: dict[str, Any] = field(default_factory=dict)


class StrategyModule(Protocol):
    """The only interface the Web application knows about a strategy."""

    descriptor: StrategyDescriptor

    def catalog_entry(self) -> dict[str, Any]: ...

    def overview(self, run_id: str | None = None) -> dict[str, Any]: ...

    def running_runs(self) -> list[dict[str, Any]]: ...

    def handle_action(
        self, action: str, body: dict[str, Any]
    ) -> StrategyOperation: ...
