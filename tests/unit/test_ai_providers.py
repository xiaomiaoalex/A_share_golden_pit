import json
from datetime import date

import pytest

from src.ai_research import DataEgressClass, ModelPolicy, ProviderResearchRequest
from src.ai_research.providers import (
    DeepSeekProvider,
    GLMProvider,
    KimiProvider,
    OpenAIProvider,
    QwenProvider,
)
from src.ai_research.providers.openai_compatible import ProviderError
from src.ai_research.repository import ResearchRepository
from src.ai_research.service import ResearchService


def test_optional_provider_capabilities_preserve_region_policy(monkeypatch):
    monkeypatch.setenv("GLM_API_KEY", "test")
    monkeypatch.setenv("KIMI_API_KEY", "test")
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    assert GLMProvider().capabilities().region == "CN"
    assert KimiProvider().capabilities().region == "CN"
    assert OpenAIProvider().capabilities().region == "US"


def _report(subject="000001 测试股份"):
    return {
        "subject": subject,
        "strategy_id": "golden-pit",
        "release_id": "release-1",
        "as_of_date": "2026-08-12",
        "thesis": "证据支持进入人工复核。",
        "verdict": "NEUTRAL",
        "confidence": 0.7,
        "findings": [
            {
                "finding_id": "finding-1",
                "claim": "候选存在",
                "evidence_ids": ["evidence-1"],
            }
        ],
        "evidence": [
            {
                "evidence_id": "evidence-1",
                "dataset_item_id": "candidate-1",
                "title": "候选记录",
                "locator": "dataset:dataset-1/candidate-1",
                "content_hash": "a" * 64,
            }
        ],
        "counter_evidence": [],
        "risks": ["需人工复核"],
        "assumptions": [],
        "data_gaps": [],
        "falsification_conditions": ["候选记录无效"],
        "recommended_actions": ["人工审核"],
    }


def _request():
    return ProviderResearchRequest(
        run_id="run-1",
        dataset_id="dataset-1",
        template_id="candidate-evidence",
        subject="000001 测试股份",
        context={
            "strategy_id": "golden-pit",
            "release_id": "release-1",
            "as_of_date": date(2026, 8, 12),
        },
    )


def test_deepseek_adapter_executes_only_registered_read_tool(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret")
    calls = []

    def transport(url, payload, headers, timeout):
        calls.append((url, payload, headers))
        if len(calls) == 1:
            return {
                "id": "response-1",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_candidate_detail",
                                        "arguments": '{"symbol":"000001"}',
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        assert payload["messages"][-1]["role"] == "tool"
        return {
            "id": "response-2",
            "choices": [{"message": {"content": json.dumps(_report())}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 30},
        }

    provider = DeepSeekProvider(transport=transport)
    result = provider.run_research(
        _request(),
        [
            {
                "type": "function",
                "function": {
                    "name": "get_candidate_detail",
                    "description": "读取候选详情",
                    "parameters": {"type": "object"},
                },
                "handler": lambda arguments: {"symbol": arguments["symbol"]},
            }
        ],
        {"type": "object"},
    )

    assert result.provider_id == "deepseek"
    assert result.input_tokens == 30
    assert calls[0][2]["Authorization"] == "Bearer test-secret"
    assert "test-secret" not in json.dumps(calls[0][1])


def test_provider_rejects_major_finding_without_evidence(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-secret")
    invalid = _report()
    invalid["findings"][0]["evidence_ids"] = []
    provider = QwenProvider(
        transport=lambda *args: {
            "choices": [{"message": {"content": json.dumps(invalid)}}]
        }
    )

    with pytest.raises(ProviderError) as exc:
        provider.run_research(_request(), [], {"type": "object"})
    assert exc.value.category == "INVALID_STRUCTURED_OUTPUT"


def test_transient_deepseek_failure_falls_back_to_qwen(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-secret")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qwen-secret")
    deepseek = DeepSeekProvider(
        transport=lambda *args: (_ for _ in ()).throw(
            ProviderError("TRANSIENT_PROVIDER_ERROR", "temporary")
        )
    )
    qwen = QwenProvider(
        transport=lambda *args: {
            "id": "qwen-response",
            "choices": [{"message": {"content": json.dumps(_report())}}],
        }
    )
    repository = ResearchRepository(tmp_path / "fallback.db")
    repository.migrate()
    repository.create_dataset(
        dataset_id="dataset-1",
        strategy_id="golden-pit",
        release_id="release-1",
        as_of_date="2026-08-12",
        content_hash="a" * 64,
        egress_class=DataEgressClass.DOMESTIC_ALLOWED,
        manifest={},
    )
    template = repository.add_template_version(
        template_id="candidate-evidence",
        version=1,
        prompt="research",
        output_schema={},
        model_policy={},
    )
    run_id = repository.start_run("dataset-1", template, "000001 测试股份")
    request = _request()
    request = request.__class__(**{**request.__dict__, "run_id": run_id})

    report_id = ResearchService(repository).execute(
        request,
        [deepseek, qwen],
        ModelPolicy(
            policy_id="cn-default", version=1, routes=("deepseek", "qwen")
        ),
        egress=DataEgressClass.DOMESTIC_ALLOWED,
    )

    assert repository.get_report(report_id)["status"] == "DRAFT"
    with repository._connect() as connection:
        provider_id = connection.execute(
            "SELECT provider_id FROM research_runs WHERE run_id=?", (run_id,)
        ).fetchone()[0]
    assert provider_id == "qwen"
