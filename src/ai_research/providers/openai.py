"""Explicitly enabled overseas comparison provider."""

from __future__ import annotations

import os

from ..contracts import ModelCapability
from .openai_compatible import OpenAICompatibleProvider, ProviderSettings


class OpenAIProvider(OpenAICompatibleProvider):
    def __init__(self, *, transport=None) -> None:
        model = os.environ.get("OPENAI_MODEL", "gpt-5-mini")
        super().__init__(
            ProviderSettings(
                provider_id="openai", model_id=model,
                base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                api_key=os.environ.get("OPENAI_API_KEY", ""), region="US",
            ),
            ModelCapability(
                provider_id="openai", model_id=model, region="US",
                tool_calling=True, structured_output=True,
                context_tokens=int(os.environ.get("OPENAI_CONTEXT_TOKENS", "128000")),
                adapter_version="1.0",
            ),
            transport=transport,
        )
