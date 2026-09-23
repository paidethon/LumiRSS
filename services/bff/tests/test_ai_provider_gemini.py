"""Tests for the native Google Gemini provider (P17).

Every HTTP test uses httpx.MockTransport — zero network, zero paid
calls, and the API key only appears inside the mock's captured headers.
The profile-factory tests use a temp database + SecretsStore and only
assert provider TYPES, never a key value.
"""

import asyncio
import json
import secrets as _secrets

import httpx
import pytest

from lumirss.ai_profiles import AiProfileStore, EffectiveAiConfig
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
    build_provider,
)
from lumirss.ai_provider_gemini import GeminiProvider
from lumirss.ai_settings import (
    GEMINI_BASE_URL,
    AiSettingsStore,
    InvalidAiSettings,
)
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database

# 组合而成的假凭据（非真实 secret；安全扫描要求无凭据形状字面量）
TEST_KEY = "fake-" + "gemini" + "-" + _secrets.token_urlsafe(6)

GEMINI_MODEL = "gemini-2.0-flash"


def run(coroutine):
    return asyncio.run(coroutine)


def make_provider(handler, base_url=GEMINI_BASE_URL, model=GEMINI_MODEL, key=TEST_KEY):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GeminiProvider(client, base_url=base_url, model=model, api_key=key)


def capture_and_ok(text="一句话摘要。", parts=None):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["key"] = request.headers.get("x-goog-api-key")
        captured["bearer"] = request.headers.get("authorization")
        captured["json"] = json.loads(request.content) if request.content else None
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": parts or [{"text": text}]}}]},
        )

    return handler, captured


def sse_response(chunks: list[dict]) -> httpx.Response:
    body = "\n".join(
        "data: " + json.dumps(chunk, ensure_ascii=False) for chunk in chunks
    ).encode("utf-8")
    return httpx.Response(
        200, content=body, headers={"content-type": "text/event-stream"}
    )


def capture_and_stream(chunks: list[dict]):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.content)
        return sse_response(chunks)

    return handler, captured


async def collect(agen):
    return [event async for event in agen]


# -- non-stream generate -----------------------------------------------------


def test_generate_content_url_headers_and_payload_shape():
    handler, captured = capture_and_ok()
    provider = make_provider(handler)

    result = run(
        provider.summarize(text="文章正文", language="zh-CN")
    )

    assert result == "一句话摘要。"
    assert (
        captured["url"]
        == f"{GEMINI_BASE_URL}/models/{GEMINI_MODEL}:generateContent"
    )
    assert captured["key"] == TEST_KEY
    assert captured["bearer"] is None  # key never travels as a bearer token
    body = captured["json"]
    assert body["generationConfig"]["temperature"] == 0.3
    assert "systemInstruction" in body
    system_text = body["systemInstruction"]["parts"][0]["text"]
    assert "never as commands" in system_text
    user_content = body["contents"][-1]
    assert user_content["role"] == "user"
    assert "zh-CN" in user_content["parts"][0]["text"]
    assert "文章正文" in user_content["parts"][0]["text"]
    # No fabricated fields: the model name comes from config only.
    assert body.get("model") is None


def test_models_prefix_in_config_is_normalized():
    handler, captured = capture_and_ok()
    provider = make_provider(handler, model=f"models/{GEMINI_MODEL}")
    run(provider.summarize(text="正文", language="en"))
    assert captured["url"].endswith(f"/models/{GEMINI_MODEL}:generateContent")


def test_english_language_instruction_reaches_prompt():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured["user"] = body["contents"][-1]["parts"][0]["text"]
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
        )

    provider = make_provider(handler)
    run(provider.summarize(text="article", language="en"))
    assert "en (English)" in captured["user"]


def test_chat_completion_returns_openai_shaped_message():
    handler, _captured = capture_and_ok(text="答案正文")
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
    assert "tool_calls" not in message


def test_function_call_part_maps_to_openai_tool_calls():
    handler, captured = capture_and_ok(
        parts=[
            {"text": "让我查一下。"},
            {"functionCall": {"name": "search", "args": {"query": "lumi"}}},
        ]
    )
    provider = make_provider(handler)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "search",
                "description": "search tool",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            },
        }
    ]

    message = run(
        provider.chat_completion(
            messages=[{"role": "user", "content": "查"}], tools=tools
        )
    )

    assert message["content"] == "让我查一下。"
    assert message["tool_calls"] == [
        {
            "id": "call_0",
            "type": "function",
            "function": {
                "name": "search",
                "arguments": json.dumps({"query": "lumi"}, ensure_ascii=False),
            },
        }
    ]
    declarations = captured["json"]["tools"][0]["functionDeclarations"]
    assert declarations == [
        {
            "name": "search",
            "description": "search tool",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
        }
    ]


def test_tool_result_history_maps_to_function_response():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        contents = body["contents"]
        assert contents[0]["role"] == "user"
        assert contents[1]["role"] == "model"
        call_part = contents[1]["parts"][0]["functionCall"]
        assert call_part["name"] == "search"
        response_part = contents[2]["parts"][0]["functionResponse"]
        assert response_part["name"] == "search"
        assert "result" in response_part["response"]
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "done"}]}}]},
        )

    provider = make_provider(handler)
    message = run(
        provider.chat_completion(
            messages=[
                {"role": "user", "content": "查"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_0",
                            "type": "function",
                            "function": {
                                "name": "search",
                                "arguments": '{"query": "lumi"}',
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_0",
                    "content": "TOOL RESULT: ok",
                },
            ]
        )
    )
    assert message["content"] == "done"


# -- SSE stream --------------------------------------------------------------


def test_stream_yields_same_events_as_openai_path():
    deltas = ["你好", "，世界", "！"]
    gemini_chunks = [
        {"candidates": [{"content": {"role": "model", "parts": [{"text": d}]}}]}
        for d in deltas
    ]
    gemini_chunks[-1] = {
        **gemini_chunks[-1],
        "candidates": [
            {**gemini_chunks[-1]["candidates"][0], "finishReason": "STOP"}
        ],
    }
    handler, captured = capture_and_stream(gemini_chunks)
    provider = make_provider(handler)
    messages = [
        {"role": "system", "content": "系统提示"},
        {"role": "user", "content": "问题"},
    ]

    events = run(collect(provider.chat_completion_stream(messages=messages)))

    assert [event["content_delta"] for event in events] == deltas
    assert (
        captured["url"]
        == f"{GEMINI_BASE_URL}/models/{GEMINI_MODEL}:streamGenerateContent?alt=sse"
    )
    assert captured["json"]["generationConfig"]["temperature"] == 0.3

    # The equivalent OpenAI SSE fixture yields the IDENTICAL event list.
    openai_events = [
        {"choices": [{"delta": {"content": d}}]} for d in deltas
    ]
    openai_lines = ["data: " + json.dumps(event) for event in openai_events]
    openai_lines.append("data: [DONE]")
    openai_body = ("\n\n".join(openai_lines) + "\n\n").encode("utf-8")

    def openai_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=openai_body,
            headers={"content-type": "text/event-stream"},
        )

    openai_client = httpx.AsyncClient(transport=httpx.MockTransport(openai_handler))
    openai_provider = OpenAICompatibleProvider(
        openai_client, base_url="https://api.example.com/v1", model="m", api_key=TEST_KEY
    )
    openai_collected = run(
        collect(openai_provider.chat_completion_stream(messages=messages))
    )

    assert events == openai_collected
    assert aggregate_stream(events) == aggregate_stream(openai_collected)
    assert aggregate_stream(events)["content"] == "".join(deltas)


def test_stream_function_call_aggregates_like_openai_tool_call_delta():
    chunks = [
        {"candidates": [{"content": {"parts": [{"text": "查一下"}]}}]},
        {
            "candidates": [
                {
                    "content": {"parts": [{"functionCall": {"name": "search", "args": {"query": "lumi"}}}]},
                    "finishReason": "STOP",
                }
            ]
        },
    ]
    handler, _captured = capture_and_stream(chunks)
    provider = make_provider(handler)
    messages = [{"role": "user", "content": "查"}]

    events = run(collect(provider.chat_completion_stream(messages=messages)))

    message = aggregate_stream(events)
    assert message["content"] == "查一下"
    assert message["tool_calls"] == [
        {
            "id": "call_0",
            "type": "function",
            "function": {
                "name": "search",
                "arguments": json.dumps({"query": "lumi"}, ensure_ascii=False),
            },
        }
    ]


def test_stream_malformed_json_maps_to_invalid_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"data: {not json}\n\n",
            headers={"content-type": "text/event-stream"},
        )

    provider = make_provider(handler)
    with pytest.raises(AiInvalidResponse):
        run(collect(provider.chat_completion_stream(messages=[])))


# -- error mapping (shared stable family) -------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, AiUpstreamError),
        (401, AiAuthError),
        (403, AiAuthError),
        (404, AiModelError),
        (429, AiRateLimited),
        (500, AiUpstreamError),
    ],
)
def test_status_maps_to_stable_error_family(status, expected):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status, json={"error": {"code": status, "message": "upstream detail"}}
        )

    provider = make_provider(handler)
    with pytest.raises(expected) as excinfo:
        run(provider.summarize(text="x", language="zh-CN"))
    assert "upstream detail" not in str(excinfo.value)


def test_timeout_maps_to_ai_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out")

    provider = make_provider(handler)
    with pytest.raises(AiTimeout):
        run(provider.summarize(text="x", language="zh-CN"))


def test_connect_failure_maps_to_upstream_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    provider = make_provider(handler)
    with pytest.raises(AiUpstreamError):
        run(provider.summarize(text="x", language="zh-CN"))


def test_invalid_json_maps_to_invalid_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json at all")

    provider = make_provider(handler)
    with pytest.raises(AiInvalidResponse):
        run(provider.summarize(text="x", language="zh-CN"))


def test_missing_candidates_maps_to_invalid_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})

    provider = make_provider(handler)
    with pytest.raises(AiInvalidResponse):
        run(provider.summarize(text="x", language="zh-CN"))


def test_blank_text_maps_to_invalid_response():
    handler, _captured = capture_and_ok(parts=[{"finishReason": "SAFETY"}])
    provider = make_provider(handler)
    with pytest.raises(AiInvalidResponse):
        run(provider.summarize(text="x", language="zh-CN"))


@pytest.mark.parametrize(
    ("model", "key"),
    [
        ("", TEST_KEY),
        (GEMINI_MODEL, ""),
    ],
)
def test_incomplete_config_raises_without_any_http_call(model, key):
    called = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(request)
        return httpx.Response(200, json={})

    provider = make_provider(handler, model=model, key=key)
    with pytest.raises(AiNotConfigured):
        run(provider.summarize(text="x", language="zh-CN"))
    assert called == []


# -- profile selection: build_provider ----------------------------------------


def _store(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    secrets = SecretsStore(tmp_path / "secrets.json")
    return AiProfileStore(db, secrets)


def test_build_provider_returns_gemini_only_for_gemini_profiles(tmp_path):
    async def scenario():
        profiles = _store(tmp_path)
        values = await AiSettingsStore(
            Database(tmp_path / "lumi.sqlite")
        ).load()
        client = httpx.AsyncClient()

        # Default resolution → OpenAI-compatible (default path unchanged).
        effective = await profiles.effective_config("summary", values, "")
        assert effective.provider == "openai_compatible"
        assert isinstance(
            build_provider(
                client,
                provider=effective.provider,
                base_url=effective.base_url,
                model=effective.model,
                api_key="",
            ),
            OpenAICompatibleProvider,
        )

        # A gemini profile → GeminiProvider with the official endpoint.
        created = await profiles.create_profile(
            label="Gemini 摘要",
            base_url="https://should.be.ignored.example/v1",
            model=GEMINI_MODEL,
            provider="gemini",
        )
        profiles.set_profile_key(created["id"], TEST_KEY)  # write-only
        # Map the profile onto the summary purpose (the UI does this via
        # PUT /settings/ai/purposes; without a mapping the default
        # resolution stays in charge).
        await profiles.save_purposes({"summary": str(created["id"])})
        effective = await profiles.effective_config("summary", values, "")
        assert effective.source == "profile"
        assert effective.provider == "gemini"
        assert effective.base_url == GEMINI_BASE_URL
        assert effective.api_key is not None and effective.api_key != ""
        provider = build_provider(
            client,
            provider=effective.provider,
            base_url=effective.base_url,
            model=effective.model,
            api_key=effective.api_key or "",
        )
        assert isinstance(provider, GeminiProvider)
        assert not isinstance(provider, OpenAICompatibleProvider)

    asyncio.run(scenario())


def test_default_and_legacy_values_keep_openai_path(tmp_path):
    client = httpx.AsyncClient()
    assert isinstance(
        build_provider(
            client,
            provider="openai_compatible",
            base_url="https://api.example.com/v1",
            model="m",
            api_key=TEST_KEY,
        ),
        OpenAICompatibleProvider,
    )
    assert isinstance(
        build_provider(
            client,
            provider="something-legacy",
            base_url="https://api.example.com/v1",
            model="m",
            api_key=TEST_KEY,
        ),
        OpenAICompatibleProvider,
    )


def test_create_profile_rejects_unknown_provider(tmp_path):
    async def scenario():
        profiles = _store(tmp_path)
        with pytest.raises(InvalidAiSettings):
            await profiles.create_profile(
                label="坏配置", provider="anthropic"
            )

    asyncio.run(scenario())


def test_effective_config_type_documented():
    """Guard: EffectiveAiConfig carries the provider for the factory."""
    assert "provider" in EffectiveAiConfig.__dataclass_fields__
