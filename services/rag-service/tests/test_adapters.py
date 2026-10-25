from __future__ import annotations

import json

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.adapters.claude_adapter import ClaudeAdapter
from app.adapters.factory import create_llm_adapter
from app.adapters.ollama_adapter import OllamaAdapter
from app.adapters.openai_adapter import OpenAIAdapter
from shared.exceptions import LLMProviderError


@respx.mock
async def test_ollama_generate_strips_think_and_reports_tokens():
    route = respx.post("http://ollama.test/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "gemma4:31b-cloud",
                "message": {"content": "<think>razonando...</think>\n1. Paso uno [Fuente: A, fragmento 1]"},
                "prompt_eval_count": 120,
                "eval_count": 30,
            },
        )
    )
    adapter = OllamaAdapter("http://ollama.test/", "gemma4:31b-cloud", think=False)
    result = await adapter.generate("sistema", "usuario", temperature=0.2, max_tokens=256)

    assert result.text == "1. Paso uno [Fuente: A, fragmento 1]"
    assert (result.provider, result.model, result.tokens_input, result.tokens_output) == ("ollama", "gemma4:31b-cloud", 120, 30)
    sent = json.loads(route.calls.last.request.content)
    assert sent["messages"][0] == {"role": "system", "content": "sistema"}
    assert sent["options"] == {"temperature": 0.2, "num_predict": 256}
    assert sent["think"] is False and sent["stream"] is False
    await adapter.aclose()


@respx.mock
async def test_ollama_omits_think_when_not_configured():
    route = respx.post("http://ollama.test/api/chat").mock(return_value=httpx.Response(200, json={"message": {"content": "ok"}}))
    await OllamaAdapter("http://ollama.test", "m").generate("s", "u")
    assert "think" not in json.loads(route.calls.last.request.content)


@respx.mock
async def test_ollama_payment_required_is_reported():
    respx.post("http://ollama.test/api/chat").mock(return_value=httpx.Response(402, text="This model is not in the Free plan"))
    with pytest.raises(LLMProviderError) as exc:
        await OllamaAdapter("http://ollama.test", "glm-5.3:cloud").generate("s", "u")
    assert exc.value.details["status"] == 402
    assert "Free plan" in exc.value.details["body"]


@respx.mock
async def test_ollama_connection_and_timeout_errors():
    route = respx.post("http://ollama.test/api/chat").mock(side_effect=httpx.ConnectError("down"))
    adapter = OllamaAdapter("http://ollama.test", "m")
    with pytest.raises(LLMProviderError) as exc:
        await adapter.generate("s", "u")
    assert exc.value.code == "llm_unavailable"
    route.mock(side_effect=httpx.ReadTimeout("lento"))
    with pytest.raises(LLMProviderError) as exc:
        await adapter.generate("s", "u")
    assert exc.value.code == "llm_timeout"


@respx.mock
async def test_ollama_health():
    route = respx.get("http://ollama.test/api/version").mock(return_value=httpx.Response(200, json={"version": "0.40"}))
    adapter = OllamaAdapter("http://ollama.test", "m")
    assert await adapter.health() is True
    route.mock(side_effect=httpx.ConnectError("down"))
    assert await adapter.health() is False


@respx.mock
async def test_claude_generate():
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "claude-sonnet-5-5",
                "content": [{"type": "text", "text": "Respuesta "}, {"type": "text", "text": "citada"}],
                "usage": {"input_tokens": 50, "output_tokens": 7},
            },
        )
    )
    adapter = ClaudeAdapter("sk-ant-test", "claude-sonnet-5-5")
    result = await adapter.generate("sistema", "usuario", max_tokens=300)
    request = route.calls.last.request
    body = json.loads(request.content)

    assert result.text == "Respuesta citada"
    assert (result.tokens_input, result.tokens_output) == (50, 7)
    assert request.headers["x-api-key"] == "sk-ant-test"
    assert request.headers["anthropic-version"] == "2023-06-01"
    assert body["system"] == "sistema" and body["max_tokens"] == 300
    assert body["messages"] == [{"role": "user", "content": "usuario"}]


@respx.mock
async def test_claude_health():
    respx.get("https://api.anthropic.com/v1/models").mock(return_value=httpx.Response(200, json={"data": []}))
    assert await ClaudeAdapter("k", "m").health() is True


@respx.mock
async def test_openai_generate_and_health():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "gpt-4o-mini",
                "choices": [{"message": {"content": "Hola [Fuente: A, fragmento 1]"}}],
                "usage": {"prompt_tokens": 9, "completion_tokens": 4},
            },
        )
    )
    respx.get("https://api.openai.com/v1/models").mock(return_value=httpx.Response(401))
    adapter = OpenAIAdapter("sk-test", "gpt-4o-mini")
    result = await adapter.generate("s", "u")
    assert result.text.startswith("Hola")
    assert (result.provider, result.tokens_input, result.tokens_output) == ("openai", 9, 4)
    assert await adapter.health() is False


@pytest.mark.parametrize("cls", [ClaudeAdapter, OpenAIAdapter])
def test_cloud_adapters_require_api_key(cls):
    with pytest.raises(LLMProviderError) as exc:
        cls("", "modelo")
    assert exc.value.code == "llm_not_configured"


def test_factory_selects_provider(settings):
    assert isinstance(create_llm_adapter(settings), OllamaAdapter)
    claude = settings.model_copy(update={"llm_provider": "claude", "anthropic_api_key": SecretStr("sk-ant")})
    assert isinstance(create_llm_adapter(claude), ClaudeAdapter)
    openai = settings.model_copy(update={"llm_provider": "openai", "openai_api_key": SecretStr("sk-oa")})
    assert isinstance(create_llm_adapter(openai), OpenAIAdapter)
