"""Contract tests for OpenAICompatibleProvider.chat_completion (P0-08a/b).

The agent loop drives the CONCRETE provider over httpx.MockTransport —
the loop-level FakeProvider in test_agent.py must never be the only
thing covering it. Asserts request shape (messages/roles/tools),
Authorization handling, tool_calls parsing, SSE stream folding and the
stable error mapping.
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
    aggregate_stream,
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "search tool",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
        },
    }
]


def run(coroutine):
    return asyncio.run(coroutine)


TEST_KEY = "test-" + "credential"  # composed, never a real-looking literal


def make_provider(handler, base_url="https://api.example.com/v1", model="m", key=TEST_KEY):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatibleProvider(
        client, base_url=base_url, model=model, api_key=key
    )


def sse_response(events: list[dict]) -> httpx.Response:
    lines = []
    for event in events:
        lines.append("data: " + json.dumps(event, ensure_ascii=False))
    lines.append("data: [DONE]")
    body = ("\n\n".join(lines) + "\n\n").encode("utf-8")
    return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})


def test_chat_completion_happy_path_returns_raw_message():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "答案正文"}}]},
        )

    provider = make_provider(handler)
    message = run(
        provider.chat_completion(
            messages=[
                {"role": "system", "content": "系统提示"},
                {"role": "user", "content": "问题"},
            ]
        )
    )

    assert message["content"] == "答案正文"
    assert captured["url"] == "https://api.example.com/v1/chat/completions"
    assert captured["auth"] == "Bearer " + TEST_KEY
    body = captured["json"]
    assert body["model"] == "m"
    assert body["stream"] is False
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["role"] == "user"


def test_chat_completion_sends_tools_payload():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "search",
                                        "arguments": '{"query": "vLLM"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    provider = make_provider(handler)
    message = run(
        provider.chat_completion(messages=[{"role": "user", "content": "搜"}], tools=TOOLS)
    )

    assert captured["json"]["tools"] == TOOLS
    calls = message["tool_calls"]
    assert calls[0]["id"] == "call_1"
    assert calls[0]["function"]["name"] == "search"
    assert json.loads(calls[0]["function"]["arguments"]) == {"query": "vLLM"}


def test_chat_completion_without_tools_omits_key():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = make_provider(handler)
    run(provider.chat_completion(messages=[{"role": "user", "content": "hi"}]))
    assert "tools" not in captured["json"]


def test_chat_completion_error_mapping():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    provider = make_provider(handler)
    with pytest.raises(AiAuthError):
        run(provider.chat_completion(messages=[{"role": "user", "content": "x"}]))


def test_chat_completion_stream_folds_deltas_and_asserts_request_shape():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        return sse_response(
            [
                {"choices": [{"delta": {"role": "assistant", "content": "你"}}]},
                {"choices": [{"delta": {"content": "好，"}}]},
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_9",
                                        "function": {
                                            "name": "search",
                                            "arguments": '{"query":',
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {"arguments": ' "vLLM"}'},
                                    }
                                ]
                            }
                        }
                    ]
                },
                {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
            ]
        )

    provider = make_provider(handler)

    async def collect():
        events = []
        async for event in provider.chat_completion_stream(
            messages=[{"role": "user", "content": "搜"}], tools=TOOLS
        ):
            events.append(event)
        return events

    events = run(collect())

    assert captured["json"]["stream"] is True
    assert captured["json"]["tools"] == TOOLS
    message = aggregate_stream(events)
    assert message["content"] == "你好，"
    calls = message["tool_calls"]
    assert calls[0]["id"] == "call_9"
    assert calls[0]["function"]["name"] == "search"
    assert json.loads(calls[0]["function"]["arguments"]) == {"query": "vLLM"}


def test_stream_maps_auth_error_before_first_byte():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    provider = make_provider(handler)

    async def consume():
        async for _event in provider.chat_completion_stream(
            messages=[{"role": "user", "content": "x"}]
        ):
            pass

    with pytest.raises(AiAuthError):
        run(consume())


def test_stream_malformed_chunk_maps_to_invalid_response():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"data: {broken json}\n\n",
            headers={"content-type": "text/event-stream"},
        )

    provider = make_provider(handler)

    async def consume():
        async for _event in provider.chat_completion_stream(
            messages=[{"role": "user", "content": "x"}]
        ):
            pass

    with pytest.raises(AiInvalidResponse):
        run(consume())


def test_stream_rate_limited_and_model_error_mapping():
    async def handler429(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    async def handler404(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    async def consume(provider):
        async for _event in provider.chat_completion_stream(
            messages=[{"role": "user", "content": "x"}]
        ):
            pass

    with pytest.raises(AiRateLimited):
        run(consume(make_provider(handler429)))
    with pytest.raises(AiModelError):
        run(consume(make_provider(handler404)))


def test_stream_timeout_and_connect_error_mapping():
    async def handler_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out")

    async def handler_connect(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    async def consume(provider):
        async for _event in provider.chat_completion_stream(
            messages=[{"role": "user", "content": "x"}]
        ):
            pass

    with pytest.raises(AiTimeout):
        run(consume(make_provider(handler_timeout)))
    with pytest.raises(AiUpstreamError):
        run(consume(make_provider(handler_connect)))


def test_unconfigured_provider_raises_before_any_http_call():
    called = []

    async def handler(request: httpx.Request) -> httpx.Response:
        called.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    provider = make_provider(handler, base_url="", model="m", key="sk-test")
    with pytest.raises(AiNotConfigured):
        run(provider.chat_completion(messages=[{"role": "user", "content": "x"}]))
    with pytest.raises(AiNotConfigured):
        run(
            provider.chat_completion_stream(
                messages=[{"role": "user", "content": "x"}]
            ).__anext__()
        )
    assert called == []
