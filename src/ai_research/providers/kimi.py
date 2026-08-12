"""Kimi provider through its OpenAI-compatible endpoint."""

from __future__ import annotations

import os

from ..contracts import ModelCapability
from .openai_compatible import OpenAICompatibleProvider, ProviderSettings


class KimiProvider(OpenAICompatibleProvider):
    def __init__(self, *, transport=None) -> None:
        model = os.environ.get("KIMI_MODEL", "moonshot-v1-128k")
        super().__init__(
            ProviderSettings(
                provider_id="kimi", model_id=model,
                base_url=os.environ.get("KIMI_BASE_URL", "https://api.moonshot.cn/v1"),
                api_key=os.environ.get("KIMI_API_KEY", ""),
            ),
            ModelCapability(
                provider_id="kimi", model_id=model, region="CN",
                tool_calling=True, structured_output=True,
                context_tokens=int(os.environ.get("KIMI_CONTEXT_TOKENS", "128000")),
                adapter_version="1.0",
            ),
            transport=transport,
        )
