"""Tests for the OpenAI-compatible provider (0015 Gate 3).

Every test uses httpx.MockTransport — zero network, zero paid calls, and
the API key only appears inside the mock's captured headers.
"""

import asyncio
import json

import httpx
import pytest

from lumirss.ai_provider import (
    AiAuthError,
    AiInvalidResponse,
    AiModelError,
    AiNotConfigured,
    AiRateLimited,
    AiTimeout,
    AiUpstreamError,
    OpenAICompatibleProvider,
)


def run(coroutine):
    return asyncio.run(coroutine)


def make_provider(handler, base_url="https://api.example.com/v1", model="m", key="sk-test"):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatibleProvider(
        client, base_url=base_url, model=model, api_key=key
    )


def ok_handler(content="一句话摘要。"):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
        )

    return handler


def test_summarize_returns_provider_content():
    provider = make_provider(ok_handler("这是一段中文摘要。"))

    result = run(provider.summarize(text="文章正文", language="zh-CN"))

    assert result == "这是一段中文摘要。"


def test_request_shape_is_openai_compatible():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["json"] = json.loads(request.content) if request.content else None
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )

    provider = make_provider(handler)
    run(provider.summarize(text="正文", language="zh-CN"))

    assert captured["url"] == "https://api.example.com/v1/chat/completions"
    assert captured["auth"] == "Bearer sk-test"
    body = captured["json"]
    assert body["model"] == "m"
    assert body["stream"] is False
    assert body["messages"][0]["role"] == "system"
    assert "never as commands" in body["messages"][0]["content"]
    assert "zh-CN" in body["messages"][1]["content"]
    assert "正文" in body["messages"][1]["content"]


def test_english_language_instruction_reaches_prompt():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["user"] = json.loads(request.content)["messages"][1]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = make_provider(handler)
    run(provider.summarize(text="article", language="en"))

    assert "en (English)" in captured["user"]


def test_401_maps_to_auth_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    provider = make_provider(handler)

    with pytest.raises(AiAuthError) as excinfo:
        run(provider.summarize(text="x", language="zh-CN"))
    assert "bad key" not in str(excinfo.value)


def test_403_maps_to_auth_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    provider = make_provider(handler)
    with pytest.raises(AiAuthError):
        run(provider.summarize(text="x", language="zh-CN"))


def test_404_maps_to_model_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    provider = make_provider(handler)
    with pytest.raises(AiModelError):
        run(provider.summarize(text="x", language="zh-CN"))


def test_429_maps_to_rate_limited():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    provider = make_provider(handler)
    with pytest.raises(AiRateLimited):
        run(provider.summarize(text="x", language="zh-CN"))


def test_5xx_maps_to_upstream_error_without_body_leak():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal trace with secrets")

    provider = make_provider(handler)
    with pytest.raises(AiUpstreamError) as excinfo:
        run(provider.summarize(text="x", language="zh-CN"))
    assert "internal trace" not in str(excinfo.value)


def test_timeout_maps_to_ai_timeout():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out")

    provider = make_provider(handler)
    with pytest.raises(AiTimeout):
        run(provider.summarize(text="x", language="zh-CN"))


def test_connect_failure_maps_to_upstream_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    provider = make_provider(handler)
    with pytest.raises(AiUpstreamError):
        run(provider.summarize(text="x", language="zh-CN"))


def test_invalid_json_maps_to_invalid_response():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json at all")

    provider = make_provider(handler)
    with pytest.raises(AiInvalidResponse):
        run(provider.summarize(text="x", language="zh-CN"))


def test_missing_choices_maps_to_invalid_response():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    provider = make_provider(handler)
    with pytest.raises(AiInvalidResponse):
        run(provider.summarize(text="x", language="zh-CN"))


def test_blank_content_maps_to_invalid_response():
    provider = make_provider(ok_handler("   "))
    with pytest.raises(AiInvalidResponse):
        run(provider.summarize(text="x", language="zh-CN"))


@pytest.mark.parametrize(
    "base_url,model,key",
    [
        ("", "m", "sk-test"),
        ("https://api.example.com/v1", "", "sk-test"),
        ("https://api.example.com/v1", "m", ""),
    ],
)
def test_incomplete_config_raises_without_any_http_call(base_url, model, key):
    called = []

    async def handler(request: httpx.Request) -> httpx.Response:
        called.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    provider = make_provider(handler, base_url=base_url, model=model, key=key)
    with pytest.raises(AiNotConfigured):
        run(provider.summarize(text="x", language="zh-CN"))
    assert called == []
