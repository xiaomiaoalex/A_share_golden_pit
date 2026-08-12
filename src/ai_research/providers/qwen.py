"""Qwen provider; endpoint and workspace remain deployment configuration."""

from __future__ import annotations

import os

from ..contracts import ModelCapability
from .openai_compatible import OpenAICompatibleProvider, ProviderSettings


class QwenProvider(OpenAICompatibleProvider):
    def __init__(self, *, transport=None) -> None:
        model = os.environ.get("QWEN_MODEL", "qwen-plus")
        settings = ProviderSettings(
            provider_id="qwen",
            model_id=model,
            base_url=os.environ.get(
                "QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
            ),
            api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
        )
        super().__init__(
            settings,
            ModelCapability(
                provider_id="qwen",
                model_id=model,
                region="CN",
                tool_calling=True,
                structured_output=True,
                context_tokens=int(os.environ.get("QWEN_CONTEXT_TOKENS", "131072")),
                adapter_version="1.0",
            ),
            transport=transport,
        )
