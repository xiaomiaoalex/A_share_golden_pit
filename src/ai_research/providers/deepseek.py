"""DeepSeek provider with configuration-driven model identity."""

from __future__ import annotations

import os

from ..contracts import ModelCapability
from .openai_compatible import OpenAICompatibleProvider, ProviderSettings


class DeepSeekProvider(OpenAICompatibleProvider):
    def __init__(self, *, transport=None) -> None:
        model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
        settings = ProviderSettings(
            provider_id="deepseek",
            model_id=model,
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
        )
        super().__init__(
            settings,
            ModelCapability(
                provider_id="deepseek",
                model_id=model,
                region="CN",
                tool_calling=True,
                structured_output=True,
                context_tokens=int(os.environ.get("DEEPSEEK_CONTEXT_TOKENS", "65536")),
                adapter_version="1.0",
            ),
            transport=transport,
        )
