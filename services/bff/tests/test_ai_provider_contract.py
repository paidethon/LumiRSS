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


# ---------------------------------------------------------------------------
# FIX-301: network-packet boundaries are NOT message boundaries.
# The stream parser must byte-buffer across aiter_bytes() chunks and only
# treat a newline as an event delimiter — a JSON event split across two
# network chunks (including a split INSIDE a multibyte UTF-8 character)
# must reassemble into the original event.
# ---------------------------------------------------------------------------


class _ChunkedResponse:
    """Minimal streaming response stub with exact chunk control."""

    def __init__(self, chunks: list[bytes], status_code: int = 200) -> None:
        self.status_code = status_code
        self._chunks = chunks

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


class _ChunkedClient:
    """Minimal AsyncClient stub handing back the pre-built response."""

    def __init__(self, response: _ChunkedResponse) -> None:
        self._response = response
        self.captured: dict = {}

    async def post(self, url, json=None, headers=None, timeout=None):
        self.captured = {"url": url, "json": json}
        return self._response


def make_chunked_provider(chunks: list[bytes]):
    return OpenAICompatibleProvider(
        _ChunkedClient(_ChunkedResponse(chunks)),
        base_url="https://api.example.com/v1",
        model="m",
        api_key=TEST_KEY,
    )


def _stream_body(events: list[dict], *, trailing_newline: bool = True) -> bytes:
    lines = ["data: " + json.dumps(event, ensure_ascii=False) for event in events]
    body = "\n\n".join(lines)
    if trailing_newline:
        body += "\n\n"
    return body.encode("utf-8")


def _split_bytes(data: bytes, offsets: list[int]) -> list[bytes]:
    """Split ``data`` at exact byte offsets (chunk-boundary control)."""
    bounds = [0, *sorted(offsets), len(data)]
    return [
        data[start:end]
        for start, end in zip(bounds, bounds[1:], strict=False)
        if start < end
    ]


async def _collect_stream(provider):
    events = []
    async for event in provider.chat_completion_stream(
        messages=[{"role": "user", "content": "问"}]
    ):
        events.append(event)
    return events


def test_stream_reassembles_json_event_split_across_chunks():
    # One content event whose JSON is cut in the middle by a network
    # chunk boundary, plus a tool-call event likewise split.
    events = [
        {"choices": [{"delta": {"content": "跨包的答案"}}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {
                                    "name": "search",
                                    "arguments": '{"query": "分片"}',
                                },
                            }
                        ]
                    }
                }
            ]
        },
    ]
    body = _stream_body(events)
    first_line_end = body.index(b"\n")
    # Cut inside each JSON payload, never on a newline.
    chunks = _split_bytes(
        body,
        [
            body.index(b'"content"') + 4,
            first_line_end + len("\ndata: {\"cho"),
            body.index(b'"arguments"') + 10,
        ],
    )
    provider = make_chunked_provider(chunks)
    message = aggregate_stream(run(_collect_stream(provider)))
    assert message["content"] == "跨包的答案"
    assert message["tool_calls"][0]["id"] == "call_1"
    assert json.loads(message["tool_calls"][0]["function"]["arguments"]) == {
        "query": "分片"
    }


def test_stream_reassembles_utf8_multibyte_split_across_chunks():
    # The chunk boundary falls INSIDE the 3-byte UTF-8 encoding of "好".
    text = "你好，世界"
    events = [{"choices": [{"delta": {"content": text}}]}]
    body = _stream_body(events)
    hao = "好".encode()
    split_at = body.index(hao) + 1  # mid-character
    assert 0 < split_at < len(body)
    provider = make_chunked_provider(_split_bytes(body, [split_at]))
    message = aggregate_stream(run(_collect_stream(provider)))
    assert message["content"] == text


# ---------------------------------------------------------------------------
# FIX-302: a stream may end with a COMPLETE event that has no trailing
# newline — the buffered remainder must be dispatched exactly like a
# newline-terminated line (content, tool calls AND usage), never dropped.
# ---------------------------------------------------------------------------


def test_stream_final_event_without_trailing_newline_content_dispatched():
    body = _stream_body(
        [{"choices": [{"delta": {"content": "末尾事件"}}]}],
        trailing_newline=False,
    )
    provider = make_chunked_provider([body])
    message = aggregate_stream(run(_collect_stream(provider)))
    assert message["content"] == "末尾事件"


def test_stream_final_event_without_trailing_newline_tool_call_and_usage():
    events = [
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
    ]
    lines = ["data: " + json.dumps(event, ensure_ascii=False) for event in events]
    # Final event: tool-call fragment + usage, NO trailing newline.
    final = (
        "data: "
        + json.dumps(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "function": {"arguments": ' "末"}'},
                                }
                            ]
                        }
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 5},
            },
            ensure_ascii=False,
        )
    )
    body = ("\n\n".join(lines) + "\n\n" + final).encode("utf-8")
    provider = make_chunked_provider([body])

    async def collect():
        got = []
        async for event in provider.chat_completion_stream(
            messages=[{"role": "user", "content": "问"}]
        ):
            got.append(event)
        return got

    events_out = run(collect())
    message = aggregate_stream(events_out)
    # The final buffered event must not be dropped: its tool-call
    # fragment completes the call and its usage is recorded.
    calls = message["tool_calls"]
    assert calls[0]["id"] == "call_9"
    assert json.loads(calls[0]["function"]["arguments"]) == {"query": "末"}
    assert provider.last_usage == {"prompt_tokens": 3, "completion_tokens": 5}


def test_stream_done_marker_without_trailing_newline_ends_cleanly():
    body = (
        _stream_body(
            [{"choices": [{"delta": {"content": "收尾"}}]}],
            trailing_newline=False,
        )
        + b"\n\ndata: [DONE]"
    )
    provider = make_chunked_provider([body])
    message = aggregate_stream(run(_collect_stream(provider)))
    assert message["content"] == "收尾"


# ---------------------------------------------------------------------------
# FIX-303 (baseline verification): an HTTP 200 response whose BODY is a
# provider business-error object must raise the stable invalid-response
# family — never be persisted as a successful artifact.
# ---------------------------------------------------------------------------


def test_complete_http_200_error_body_raises_invalid_response():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"error": {"message": "insufficient quota", "type": "server_error"}},
        )

    provider = make_provider(handler)
    with pytest.raises(AiInvalidResponse):
        run(provider.complete(messages=[{"role": "user", "content": "x"}]))


def test_chat_completion_http_200_error_body_raises_invalid_response():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"error": {"message": "model overloaded", "code": "503"}},
        )

    provider = make_provider(handler)
    with pytest.raises(AiInvalidResponse):
        run(provider.chat_completion(messages=[{"role": "user", "content": "x"}]))
