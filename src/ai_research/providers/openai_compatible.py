"""HTTP adapter base for vendor-specific OpenAI-compatible chat endpoints."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Mapping, Sequence

from ..contracts import (
    AIProviderPort,
    EvidenceReference,
    ModelCapability,
    ProviderResearchRequest,
    ProviderResearchResult,
    ResearchFinding,
    ResearchReport,
    ResearchVerdict,
)


class ProviderError(RuntimeError):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class ProviderSettings:
    provider_id: str
    model_id: str
    base_url: str
    api_key: str
    region: str = "CN"
    adapter_version: str = "1.0"
    timeout_seconds: float = 90.0
    max_tool_calls: int = 8


def report_from_mapping(value: Mapping[str, Any]) -> ResearchReport:
    return ResearchReport(
        subject=str(value["subject"]),
        strategy_id=str(value["strategy_id"]),
        release_id=str(value["release_id"]),
        as_of_date=date.fromisoformat(str(value["as_of_date"])),
        thesis=str(value["thesis"]),
        verdict=ResearchVerdict(str(value["verdict"])),
        confidence=float(value["confidence"]),
        findings=tuple(
            ResearchFinding(
                finding_id=str(item["finding_id"]),
                claim=str(item["claim"]),
                evidence_ids=tuple(map(str, item.get("evidence_ids", []))),
                is_major=bool(item.get("is_major", True)),
            )
            for item in value.get("findings", [])
        ),
        evidence=tuple(
            EvidenceReference(
                evidence_id=str(item["evidence_id"]),
                dataset_item_id=str(item["dataset_item_id"]),
                title=str(item["title"]),
                locator=str(item["locator"]),
                content_hash=str(item["content_hash"]),
            )
            for item in value.get("evidence", [])
        ),
        counter_evidence=tuple(map(str, value.get("counter_evidence", []))),
        risks=tuple(map(str, value.get("risks", []))),
        assumptions=tuple(map(str, value.get("assumptions", []))),
        data_gaps=tuple(map(str, value.get("data_gaps", []))),
        falsification_conditions=tuple(
            map(str, value.get("falsification_conditions", []))
        ),
        recommended_actions=tuple(map(str, value.get("recommended_actions", []))),
        schema_version=str(value.get("schema_version", "research-report-v1")),
    )


class OpenAICompatibleProvider(AIProviderPort):
    """Bounded tool loop with mandatory local parsing and evidence validation."""

    def __init__(
        self,
        settings: ProviderSettings,
        capability: ModelCapability,
        *,
        transport: Callable[[str, dict[str, Any], dict[str, str], float], dict] | None = None,
    ) -> None:
        self.settings = settings
        self._capability = capability
        self._transport = transport or self._http_transport

    def capabilities(self) -> ModelCapability:
        return self._capability

    def health_check(self) -> Mapping[str, Any]:
        return {
            "status": "configured" if bool(self.settings.api_key) else "not_configured",
            "provider_id": self.settings.provider_id,
            "model_id": self.settings.model_id,
            "region": self.settings.region,
        }

    def run_research(
        self,
        request: ProviderResearchRequest,
        tools: Sequence[Mapping[str, Any]],
        output_schema: Mapping[str, Any],
    ) -> ProviderResearchResult:
        if not self.settings.api_key:
            raise ProviderError("NOT_CONFIGURED", "模型 API Key 未配置")
        tool_handlers = {
            str(item["function"]["name"]): item.get("handler")
            for item in tools
            if item.get("function")
        }
        public_tools = [
            {key: value for key, value in item.items() if key != "handler"}
            for item in tools
        ]
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": "只可依据给定数据和工具生成 JSON 研究草稿；不得修改量化结论。",
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"subject": request.subject, "context": request.context},
                    ensure_ascii=False,
                    default=str,
                ),
            },
        ]
        total_input = total_output = 0
        response_id = str(uuid.uuid4())
        for _ in range(self.settings.max_tool_calls + 1):
            payload: dict[str, Any] = {
                "model": self.settings.model_id,
                "messages": messages,
                "response_format": {"type": "json_object"},
            }
            if public_tools:
                payload["tools"] = public_tools
            response = self._transport(
                f"{self.settings.base_url.rstrip('/')}/chat/completions",
                payload,
                {
                    "Authorization": f"Bearer {self.settings.api_key}",
                    "Content-Type": "application/json",
                },
                self.settings.timeout_seconds,
            )
            response_id = str(response.get("id", response_id))
            usage = response.get("usage", {})
            total_input += int(usage.get("prompt_tokens", 0))
            total_output += int(usage.get("completion_tokens", 0))
            message = response["choices"][0]["message"]
            calls = message.get("tool_calls") or []
            if calls:
                messages.append(message)
                for call in calls:
                    name = str(call["function"]["name"])
                    handler = tool_handlers.get(name)
                    if not callable(handler):
                        raise ProviderError("POLICY_BLOCKED", f"模型请求未授权工具: {name}")
                    arguments = json.loads(call["function"].get("arguments") or "{}")
                    result = handler(arguments)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": json.dumps(result, ensure_ascii=False, default=str),
                        }
                    )
                continue
            try:
                raw = json.loads(message.get("content") or "")
                report = report_from_mapping(raw)
                report.validate()
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ProviderError("INVALID_STRUCTURED_OUTPUT", str(exc)) from exc
            return ProviderResearchResult(
                report=report,
                provider_id=self.settings.provider_id,
                model_id=self.settings.model_id,
                request_id=response_id,
                input_tokens=total_input,
                output_tokens=total_output,
                cost=0.0,
            )
        raise ProviderError("TOOL_BUDGET_EXCEEDED", "模型工具调用超过模板预算")

    @staticmethod
    def _http_transport(
        url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float
    ) -> dict:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            category = "RATE_LIMITED" if exc.code == 429 else "PROVIDER_ERROR"
            raise ProviderError(category, f"HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError("TRANSIENT_PROVIDER_ERROR", str(exc)) from exc
