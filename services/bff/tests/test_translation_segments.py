"""Per-block (bilingual) translation tests: cache identity, batching,
honest failure rows, LibreTranslate adapter, and the money rules.

Providers and HTTP are always faked — these tests never touch a real
translation service, and API keys never enter any cache key.
"""

import asyncio
import json

import httpx
import pytest

from lumirss.ai_provider import AiTimeout
from lumirss.ai_settings import (
    LIBRETRANSLATE_KEY_NAME,
    AiSettingsUpdate,
)
from lumirss.ai_translation_segments import (
    MAX_BLOCKS,
    SEGMENTS_PROMPT_VERSION,
    SegmentInput,
    SegmentTranslationService,
    SegmentTranslationUnavailable,
    block_hash,
    normalize_block_text,
    parse_segment_batch,
)
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database


def run(coroutine):
    return asyncio.run(coroutine)


def _marker(index: int) -> str:
    return f"<<<BLOCK {index}>>>"


def _make_service(tmp_path, provider_factory=None, transport=None):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    from lumirss.ai_settings import AiSettingsStore

    settings = AiSettingsStore(db)
    secrets = SecretsStore(tmp_path / "secrets.json")
    httpx_factory = (
        (lambda: httpx.AsyncClient(transport=transport))
        if transport is not None
        else None
    )
    service = SegmentTranslationService(
        db=db,
        settings_store=settings,
        provider_factory=provider_factory or _never_provider,
        secrets=secrets,
        httpx_client_factory=httpx_factory,
    )
    return service, settings, secrets


async def _never_provider(base_url, model):
    raise AssertionError("provider must never be built in this flow")


BLOCKS = [
    SegmentInput(index=0, text="First paragraph body."),
    SegmentInput(index=1, text="Second paragraph body."),
    SegmentInput(index=2, text="Third paragraph body."),
]


# ---------------------------------------------------------------------------
# parse_segment_batch
# ---------------------------------------------------------------------------


def test_parse_batch_splits_all_blocks():
    raw = (
        f"{_marker(0)}\n第一段。\n\n{_marker(1)}\n第二段。\n\n{_marker(2)}\n第三段。"
    )
    result = parse_segment_batch(raw, [0, 1, 2])
    assert result == {0: "第一段。", 1: "第二段。", 2: "第三段。"}


def test_parse_batch_missing_marker_invalidates_whole_batch():
    raw = f"{_marker(0)}\n第一段。\n\n{_marker(2)}\n第三段。"
    assert parse_segment_batch(raw, [0, 1, 2]) == {}


def test_parse_batch_empty_block_invalidates_whole_batch():
    raw = f"{_marker(0)}\n第一段。\n\n{_marker(1)}\n   \n"
    assert parse_segment_batch(raw, [0, 1]) == {}


# ---------------------------------------------------------------------------
# bounds validation
# ---------------------------------------------------------------------------


def test_validate_rejects_empty_and_duplicate_and_oversize(tmp_path):
    service, _, _ = _make_service(tmp_path)
    with pytest.raises(SegmentTranslationUnavailable):
        service._validate_blocks([])
    with pytest.raises(SegmentTranslationUnavailable):
        service._validate_blocks(
            [SegmentInput(index=0, text="x"), SegmentInput(index=0, text="y")]
        )
    with pytest.raises(SegmentTranslationUnavailable):
        service._validate_blocks(
            [SegmentInput(index=MAX_BLOCKS, text="x")]
        )


def test_validate_drops_whitespace_only_blocks(tmp_path):
    service, _, _ = _make_service(tmp_path)
    clean = service._validate_blocks(
        [SegmentInput(index=0, text="   "), SegmentInput(index=1, text="real")]
    )
    assert [b.index for b in clean] == [1]


# ---------------------------------------------------------------------------
# money rules + AI generation
# ---------------------------------------------------------------------------


def test_lookup_never_calls_provider(tmp_path):
    service, settings, _ = _make_service(tmp_path)  # factory raises if used
    states = run(service.lookup("e1.itest", BLOCKS))
    assert [s.status for s in states] == ["not_generated"] * 3


def test_generate_then_exact_cache_hit(tmp_path):
    calls = {"n": 0}

    async def factory(base_url, model):
        calls["n"] += 1

        class FakeProvider:
            async def complete(self, messages):
                return (
                    f"{_marker(0)}\n第一段。\n\n{_marker(1)}\n第二段。\n\n"
                    f"{_marker(2)}\n第三段。"
                )

        return FakeProvider()

    service, settings, _ = _make_service(tmp_path, provider_factory=factory)
    run(settings.save(AiSettingsUpdate(baseUrl="http://127.0.0.1:9999/v1", model="m1")))

    first = run(service.generate("e1.itest", BLOCKS))
    assert [s.status for s in first] == ["success"] * 3
    assert [s.cached for s in first] == [False, False, False]
    assert calls["n"] == 1

    # exact cache hit: no provider construction, no provider call
    second = run(service.generate("e1.itest", BLOCKS))
    assert [s.cached for s in second] == [True, True, True]
    assert calls["n"] == 1

    # different text => different hash => regenerated (per-block)
    changed = [BLOCKS[0], SegmentInput(index=1, text="Second paragraph EDITED."), BLOCKS[2]]
    third = run(service.generate("e1.itest", changed))
    assert third[1].cached is False
    assert third[0].cached is True
    assert calls["n"] == 2


def test_generate_invalid_response_marks_failed_then_retry(tmp_path):
    calls = {"n": 0}

    async def factory(base_url, model):
        calls["n"] += 1

        class FakeProvider:
            def __init__(self, broken):
                self.broken = broken

            async def complete(self, messages):
                if self.broken:
                    return "模型没按格式返回的一段话"
                return f"{_marker(0)}\n第一段。\n\n{_marker(1)}\n第二段。"

        return FakeProvider(calls["n"] == 1)

    service, settings, _ = _make_service(tmp_path, provider_factory=factory)
    run(settings.save(AiSettingsUpdate(baseUrl="http://127.0.0.1:9999/v1", model="m1")))

    failed = run(service.generate("e1.itest", BLOCKS[:2]))
    assert [s.status for s in failed] == ["failed", "failed"]
    assert failed[0].failure_type == "invalid_response"

    fixed = run(service.generate("e1.itest", BLOCKS[:2]))
    assert [s.status for s in fixed] == ["success", "success"]
    assert calls["n"] == 2


def test_generate_provider_error_persists_failure_type(tmp_path):
    async def factory(base_url, model):
        class FakeProvider:
            async def complete(self, messages):
                raise AiTimeout("upstream timeout")

        return FakeProvider()

    service, settings, _ = _make_service(tmp_path, provider_factory=factory)
    run(settings.save(AiSettingsUpdate(baseUrl="http://127.0.0.1:9999/v1", model="m1")))
    failed = run(service.generate("e1.itest", BLOCKS[:1]))
    assert failed[0].status == "failed"
    assert failed[0].failure_type == "timeout"


def test_generate_requires_ai_config(tmp_path):
    service, settings, _ = _make_service(tmp_path)  # defaults: no base/model
    from lumirss.ai_provider import AiNotConfigured

    with pytest.raises(AiNotConfigured):
        run(service.generate("e1.itest", BLOCKS[:1]))


def test_browser_engine_refused(tmp_path):
    service, settings, _ = _make_service(tmp_path)
    run(settings.save(AiSettingsUpdate(translationEngine="browser")))
    with pytest.raises(SegmentTranslationUnavailable):
        run(service.generate("e1.itest", BLOCKS[:1]))


def test_block_limit_enforced(tmp_path):
    service, settings, _ = _make_service(tmp_path)
    run(settings.save(AiSettingsUpdate(baseUrl="http://127.0.0.1:9999/v1", model="m1")))
    too_many = [SegmentInput(index=i, text=f"block {i}") for i in range(MAX_BLOCKS + 1)]
    with pytest.raises(SegmentTranslationUnavailable):
        run(service.generate("e1.itest", too_many))


# ---------------------------------------------------------------------------
# LibreTranslate engine
# ---------------------------------------------------------------------------


def _libre_transport(responder):
    return httpx.MockTransport(responder)


def test_libretranslate_success(tmp_path):
    service, settings, _ = _make_service(
        tmp_path,
        transport=_libre_transport(
            lambda request: httpx.Response(
                200,
                json={"translatedText": ["第一段。", "第二段。"]},
            )
        ),
    )
    run(settings.save(AiSettingsUpdate(translationEngine="libretranslate")))
    run(settings.save(AiSettingsUpdate(libretranslateUrl="http://127.0.0.1:5000")))

    states = run(
        service.generate(
            "e1.itest",
            [SegmentInput(index=0, text="First."), SegmentInput(index=1, text="Second.")],
        )
    )
    assert [s.status for s in states] == ["success", "success"]
    assert [s.translated_text for s in states] == ["第一段。", "第二段。"]
    cached = run(
        service.lookup(
            "e1.itest",
            [SegmentInput(index=0, text="First."), SegmentInput(index=1, text="Second.")],
        )
    )
    assert [s.cached for s in cached] == [True, True]


def test_libretranslate_http_error_marks_upstream_failed(tmp_path):
    service, settings, _ = _make_service(
        tmp_path,
        transport=_libre_transport(
            lambda request: httpx.Response(500, json={"error": "boom"})
        ),
    )
    run(settings.save(AiSettingsUpdate(translationEngine="libretranslate")))
    run(settings.save(AiSettingsUpdate(libretranslateUrl="http://127.0.0.1:5000")))
    states = run(service.generate("e1.itest", [SegmentInput(index=0, text="First.")]))
    assert states[0].status == "failed"
    assert states[0].failure_type == "upstream_error"


def test_libretranslate_requires_url(tmp_path):
    service, settings, _ = _make_service(tmp_path)
    run(settings.save(AiSettingsUpdate(translationEngine="libretranslate")))
    with pytest.raises(SegmentTranslationUnavailable):
        run(service.generate("e1.itest", [SegmentInput(index=0, text="First.")]))


def test_libretranslate_sends_optional_api_key(tmp_path):
    seen = {}

    def responder(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"translatedText": ["你好。"]})

    service, settings, secrets = _make_service(
        tmp_path, transport=_libre_transport(responder)
    )
    run(settings.save(AiSettingsUpdate(translationEngine="libretranslate")))
    run(settings.save(AiSettingsUpdate(libretranslateUrl="http://127.0.0.1:5000")))
    secrets.set(LIBRETRANSLATE_KEY_NAME, "itest-key-12345")
    run(service.generate("e1.itest", [SegmentInput(index=0, text="Hello.")]))
    assert seen["body"]["api_key"] == "itest-key-12345"
    # the key never appears in cache identity inputs
    row_hash = block_hash(normalize_block_text("Hello."))
    assert "itest-key-12345" not in row_hash


def test_prompt_version_scopes_cache(tmp_path):
    assert SEGMENTS_PROMPT_VERSION != "translation-v1"


# ---------------------------------------------------------------------------
# 0021: malicious-provider-response hardening (parse_segment_batch)
# ---------------------------------------------------------------------------


def test_parse_batch_rejects_out_of_order_markers():
    raw = f"{_marker(1)}\n第二段。\n\n{_marker(0)}\n第一段。"
    assert parse_segment_batch(raw, [0, 1]) == {}


def test_parse_batch_rejects_duplicate_marker():
    raw = f"{_marker(0)}\n第一段。\n\n{_marker(0)}\n重复标记。"
    assert parse_segment_batch(raw, [0]) == {}


def test_parse_batch_rejects_extra_unrequested_marker():
    raw = f"{_marker(0)}\n第一段。\n\n{_marker(5)}\n走私块。"
    assert parse_segment_batch(raw, [0]) == {}


def test_parse_batch_inline_marker_never_splits():
    # Marker echoed inside translated prose (not on its own line) is
    # content, not a delimiter — the batch still parses by its real lines.
    raw = f"{_marker(0)}\n行内标记 >>>{_marker(1)}<<< 不应分块。"
    result = parse_segment_batch(raw, [0])
    assert result == {0: f"行内标记 >>>{_marker(1)}<<< 不应分块。"}


def test_parse_batch_accepts_trailing_whitespace_on_marker_line():
    raw = f"{_marker(0)}  \n第一段。\n{_marker(1)}\t\n第二段。"
    result = parse_segment_batch(raw, [0, 1])
    assert result == {0: "第一段。", 1: "第二段。"}


# ---------------------------------------------------------------------------
# 0021: bounded lock pool + service-level batch concurrency
# ---------------------------------------------------------------------------


def test_article_locks_use_bounded_pool(tmp_path):
    from lumirss.ai_artifacts import GenerationLockPool

    service, _settings, _secrets = _make_service(tmp_path)
    assert isinstance(service._article_locks, GenerationLockPool)
    lock_a = service._article_locks.lock_for("entry-1")
    lock_a_again = service._article_locks.lock_for("entry-1")
    assert lock_a is lock_a_again


async def _idle_provider_factory(base_url, model):
    """Provider whose complete() is never reached (batch runner stubbed)."""

    class _IdleProvider:
        async def complete(self, messages):
            raise AssertionError("complete() must not run in this flow")

    return _IdleProvider()


def test_batch_semaphore_is_service_level(tmp_path):
    """Two concurrent generate calls share ONE bounded batch budget.

    Each article splits into 3 batches (12 blocks × 3000 chars, batch cap
    12000) → 6 batch tasks in flight. A per-call semaphore would allow a
    peak of 6; the shared service-level one caps the peak at
    MAX_CONCURRENT_BATCHES.
    """
    service, settings, _secrets = _make_service(
        tmp_path, provider_factory=_idle_provider_factory
    )
    run(settings.save(AiSettingsUpdate(baseUrl="http://ai.local/v1", model="m1")))

    peak = {"concurrent": 0, "max": 0}

    async def slow_batch(entry_ref, batch, *args, **kwargs):
        peak["concurrent"] += 1
        peak["max"] = max(peak["max"], peak["concurrent"])
        await asyncio.sleep(0.05)
        peak["concurrent"] -= 1

    service._run_ai_batch = slow_batch  # type: ignore[method-assign]

    from lumirss.ai_translation_segments import MAX_CONCURRENT_BATCHES

    blocks = [
        SegmentInput(index=i, text="x" * 3000) for i in range(12)
    ]

    async def two_articles():
        await asyncio.gather(
            service.generate("entry-A", blocks),
            service.generate("entry-B", blocks),
        )

    run(two_articles())
    assert peak["max"] <= MAX_CONCURRENT_BATCHES
    assert peak["max"] >= 2
