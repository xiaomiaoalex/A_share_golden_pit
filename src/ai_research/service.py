"""Small orchestration seam used by mock and future real providers."""

from __future__ import annotations

from typing import Any, Sequence

from .contracts import (
    AIProviderPort,
    DataEgressClass,
    ModelPolicy,
    ProviderResearchRequest,
)
from .providers.openai_compatible import ProviderError
from .repository import ResearchRepository


class ResearchService:
    def __init__(self, repository: ResearchRepository) -> None:
        self.repository = repository

    def execute(
        self,
        request: ProviderResearchRequest,
        providers: Sequence[AIProviderPort],
        policy: ModelPolicy,
        *,
        egress: DataEgressClass,
        tools: Sequence[dict[str, Any]] = (),
        output_schema: dict[str, Any] | None = None,
    ) -> str:
        capabilities = [provider.capabilities() for provider in providers]
        eligible = []
        remaining = list(capabilities)
        while remaining:
            try:
                selected = policy.select(remaining, egress)
            except ValueError:
                break
            eligible.append(selected.provider_id)
            remaining = [
                item for item in remaining if item.provider_id != selected.provider_id
            ]
        last_error: ProviderError | None = None
        result = None
        for provider_id in eligible:
            provider = next(
                item
                for item in providers
                if item.capabilities().provider_id == provider_id
            )
            try:
                result = provider.run_research(request, tools, output_schema or {})
                break
            except ProviderError as exc:
                last_error = exc
                if exc.category not in {
                    "RATE_LIMITED",
                    "TRANSIENT_PROVIDER_ERROR",
                    "PROVIDER_ERROR",
                }:
                    raise
        if result is None:
            if last_error is not None:
                raise last_error
            raise ValueError("没有满足政策的可用模型 Provider")
        return self.repository.complete_run(
            request.run_id,
            result.report,
            provider_id=result.provider_id,
            model_id=result.model_id,
            usage={
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cost": result.cost,
                "request_id": result.request_id,
            },
        )
