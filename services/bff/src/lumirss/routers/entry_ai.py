"""Entry_ai routes (moved verbatim from main.py)."""



from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, field_validator

from lumirss.ai_conversation import MAX_QUESTION_CHARS
from lumirss.ai_settings import (
    KEY_TRANSLATION_ENGINE,
    KEY_TRANSLATION_LANGUAGE,
)
from lumirss.ai_translation_segments import (
    TRANSLATION_ENGINE_BROWSER,
    SegmentInput,
)
from lumirss.deps import (
    _get_conversation_service,
    _get_segment_service,
    _get_summary_service,
    _get_translation_service,
)
from lumirss.entryref import decode_entry_ref
from lumirss.models import (
    EntryConversation,
    EntrySummary,
    EntryTranslation,
    TranslationSegmentsView,
)

router = APIRouter()


class TranslationSegmentBlockIn(BaseModel):
    """One client-segmented content block."""

    index: int = Field(ge=0, le=63)
    text: str = Field(min_length=1, max_length=20000)


class TranslationSegmentsBody(BaseModel):
    """POST …/translation/segments/lookup | /generate body."""

    blocks: list[TranslationSegmentBlockIn] = Field(min_length=1, max_length=64)


def _segment_inputs(body: TranslationSegmentsBody) -> list[SegmentInput]:
    return [SegmentInput(index=b.index, text=b.text) for b in body.blocks]


def _segments_view(states, settings_values) -> dict[str, object]:
    return {
        "engine": settings_values[KEY_TRANSLATION_ENGINE],
        "targetLanguage": settings_values[KEY_TRANSLATION_LANGUAGE],
        "segments": [
            {
                "index": s.index,
                "status": s.status,
                "translatedText": s.translated_text,
                "failureType": s.failure_type,
                "cached": s.cached,
            }
            for s in states
        ],
    }


@router.post(
    "/api/v1/entries/{entry_ref}/translation/segments/lookup",
    response_model=TranslationSegmentsView,
)
async def lookup_translation_segments(
    entry_ref: str, body: TranslationSegmentsBody, request: Request
) -> dict[str, object]:
    """Cached per-block state ONLY — never calls a provider."""
    decode_entry_ref(entry_ref)  # 400 on malformed refs before any work
    service = _get_segment_service(request)
    settings_values = await service._resolve_settings()
    if settings_values[KEY_TRANSLATION_ENGINE] == TRANSLATION_ENGINE_BROWSER:
        return _segments_view([], settings_values) | {
            "engine": TRANSLATION_ENGINE_BROWSER, "segments": []
        }
    states = await service.lookup(entry_ref, _segment_inputs(body), settings_values)
    return _segments_view(states, settings_values)


@router.post(
    "/api/v1/entries/{entry_ref}/translation/segments/generate",
    response_model=TranslationSegmentsView,
)
async def generate_translation_segments(
    entry_ref: str, body: TranslationSegmentsBody, request: Request
) -> dict[str, object]:
    """Explicit generation for the bilingual/translated views (money rule:
    only this endpoint may call a provider; exact cache hits never do)."""
    decode_entry_ref(entry_ref)
    service = _get_segment_service(request)
    states = await service.generate(entry_ref, _segment_inputs(body))
    settings_values = await service._resolve_settings()
    return _segments_view(states, settings_values)


def _summary_json(state) -> dict[str, object]:
    """Browser-safe summary view — no secrets, no raw provider output."""
    return {
        "status": state.status,
        "summary": state.summary,
        "provider": state.provider,
        "model": state.model,
        "promptVersion": state.prompt_version,
        "language": state.language,
        "generatedAt": state.generated_at,
        "failureType": state.failure_type,
        "cached": state.cached,
    }


@router.get(
    "/api/v1/entries/{entry_ref}/summary",
    response_model=EntrySummary,
    response_model_exclude_none=False,  # "not_generated" → summary: null
)
async def get_entry_summary(entry_ref: str, request: Request) -> dict[str, object]:
    """Read-only summary state. NEVER calls the AI provider (no cost):
    only FreshRSS read + the Lumi cache are consulted."""
    decode_entry_ref(entry_ref)  # raises InvalidEntryReference → 400
    service = _get_summary_service(request)
    return _summary_json(await service.get_summary(entry_ref))


@router.post(
    "/api/v1/entries/{entry_ref}/summary",
    response_model=EntrySummary,
    response_model_exclude_none=False,
)
async def generate_entry_summary(
    entry_ref: str, request: Request
) -> dict[str, object]:
    """Explicit summary generation. An exact cache hit costs nothing;
    otherwise exactly one bounded provider call is made (synchronously)."""
    decode_entry_ref(entry_ref)  # raises InvalidEntryReference → 400
    service = _get_summary_service(request)
    return _summary_json(await service.generate_summary(entry_ref))


def _translation_json(state) -> dict[str, object]:
    """Browser-safe translation view — no secrets, plain text output."""
    return {
        "status": state.status,
        "translatedTitle": state.translated_title,
        "translatedText": state.translated_text,
        "provider": state.provider,
        "model": state.model,
        "promptVersion": state.prompt_version,
        "targetLanguage": state.target_language,
        "generatedAt": state.generated_at,
        "failureType": state.failure_type,
        "cached": state.cached,
    }


@router.get(
    "/api/v1/entries/{entry_ref}/translation",
    response_model=EntryTranslation,
    response_model_exclude_none=False,  # "not_generated" → translated*: null
)
async def get_entry_translation(
    entry_ref: str, request: Request
) -> dict[str, object]:
    """Read-only translation state. NEVER calls the AI provider (no cost):
    only FreshRSS read + the Lumi cache are consulted."""
    decode_entry_ref(entry_ref)  # raises InvalidEntryReference → 400
    service = _get_translation_service(request)
    return _translation_json(await service.get_translation(entry_ref))


@router.post(
    "/api/v1/entries/{entry_ref}/translation",
    response_model=EntryTranslation,
    response_model_exclude_none=False,
)
async def generate_entry_translation(
    entry_ref: str, request: Request
) -> dict[str, object]:
    """Explicit translation generation. An exact cache hit costs nothing;
    otherwise exactly one bounded provider call is made (synchronously).
    The original article is never modified or written back to FreshRSS."""
    decode_entry_ref(entry_ref)  # raises InvalidEntryReference → 400
    service = _get_translation_service(request)
    return _translation_json(await service.generate_translation(entry_ref))


class ConversationQuestion(BaseModel):
    """POST /api/v1/entries/{entryRef}/conversation/messages body (0016).

    Bounded question; blank-after-strip is rejected before any provider
    work (422 via FastAPI validation).
    """

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)

    @field_validator("question")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value


def _conversation_json(state) -> dict[str, object]:
    """Browser-safe conversation view — plain text messages only."""
    return {
        "status": state.status,
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "createdAt": message.created_at,
            }
            for message in state.messages
        ],
    }


@router.get(
    "/api/v1/entries/{entry_ref}/conversation",
    response_model=EntryConversation,
)
async def get_entry_conversation(
    entry_ref: str, request: Request
) -> dict[str, object]:
    """Read-only conversation state for this article. NEVER calls the
    provider: only FreshRSS read + the Lumi message store."""
    decode_entry_ref(entry_ref)  # raises InvalidEntryReference → 400
    service = _get_conversation_service(request)
    return _conversation_json(await service.get_conversation(entry_ref))


@router.post(
    "/api/v1/entries/{entry_ref}/conversation/messages",
    response_model=EntryConversation,
)
async def send_conversation_message(
    entry_ref: str, body: ConversationQuestion, request: Request
) -> dict[str, object]:
    """Ask one article-scoped question. Exactly one bounded provider call
    (synchronously); on success the question and the reply are persisted
    and the full conversation is returned."""
    decode_entry_ref(entry_ref)  # raises InvalidEntryReference → 400
    service = _get_conversation_service(request)
    return _conversation_json(
        await service.send_message(entry_ref, body.question)
    )


# ---------------------------------------------------------------------------
# 0018 — Operations, RSSHub Control Center, Backup / WebDAV / Restore
# ---------------------------------------------------------------------------


