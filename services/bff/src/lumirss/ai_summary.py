"""Cached article summary domain (0015 Gate 4).

Pipeline:

    FreshRSS entry detail (contentText)
        → normalize (whitespace-collapse + deterministic bound)
        → contentHash (SHA-256 of the normalized text)
        → cache identity (entryRef, contentHash, provider, model,
                          promptVersion, language)
        → exact cache hit OR one provider call
        → persist success/failure metadata in lumi.sqlite

State machine, lock pool, and failure semantics are the shared
``ai_artifacts.CachedAiArtifactService`` contract (see its docstring
for the money rules). This module keeps only the summary-specific
parts: identity resolution from the live article, the provider prompt
call, the ``ai_summaries`` statements, and the public state dataclass.
"""

import asyncio
from dataclasses import dataclass

from lumirss.ai_artifacts import (
    FAILURE_INTERRUPTED,
    STATUS_FAILED,
    STATUS_GENERATING,
    STATUS_NOT_GENERATED,
    STATUS_SUCCESS,
    AiCacheIdentity,
    AiContentUnavailable,
    CachedAiArtifactService,
    content_hash,
    is_stale_generating,
    provider_failure_type,
    require_ai_configured,
)
from lumirss.ai_artifacts import normalize_ai_content as normalize_content
from lumirss.ai_provider import (
    SUMMARY_PROMPT_VERSION,
    AiNotConfigured,
    AiProviderError,
)
from lumirss.ai_settings import (
    KEY_BASE_URL,
    KEY_MODEL,
    KEY_PROVIDER,
    KEY_SUMMARY_LANGUAGE,
)
from lumirss.util import utc_now

# The generate flow below keeps its 0015 statement text verbatim; these
# bindings route its helper calls to the shared implementations.
CacheIdentity = AiCacheIdentity
_utc_now = utc_now
_provider_failure_type = provider_failure_type

__all__ = [
    "STATUS_FAILED",
    "STATUS_GENERATING",
    "STATUS_NOT_GENERATED",
    "STATUS_SUCCESS",
    "AiCacheIdentity",
    "AiContentUnavailable",
    "SummaryService",
    "SummaryState",
    "content_hash",
    "normalize_content",
]

MAX_SUMMARY_INPUT_CHARS = 12000


@dataclass(frozen=True)
class SummaryState:
    status: str
    summary: str | None = None
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    language: str | None = None
    generated_at: str | None = None
    failure_type: str | None = None
    cached: bool = False
    input_chars: int | None = None
    truncated: bool = False


class SummaryService(CachedAiArtifactService):
    """On-demand, cached article summarization."""

    async def _resolve(self, entry_ref: str):
        from lumirss.entryref import decode_entry_ref

        item_id = decode_entry_ref(entry_ref)
        detail = await self._adapter.get_entry(item_id)
        normalized = normalize_content(detail.contentText)
        if not normalized:
            raise AiContentUnavailable(
                "This article has no text content to summarize."
            )
        settings = await self._settings.load()
        identity = AiCacheIdentity(
            entry_ref=entry_ref,
            content_hash=content_hash(normalized),
            provider=settings[KEY_PROVIDER],
            model=settings[KEY_MODEL],
            prompt_version=SUMMARY_PROMPT_VERSION,
            language=settings[KEY_SUMMARY_LANGUAGE],
        )
        return normalized, identity

    async def _fetch_row(self, identity: CacheIdentity):
        await self._db.migrate()
        return await self._db.fetch_one(
            "SELECT * FROM ai_summaries WHERE entry_ref = ? AND content_hash = ? "
            "AND provider = ? AND model = ? AND prompt_version = ? AND language = ?",
            identity.row_params(),
        )

    def _state_from_row(
        self,
        row,
        *,
        cached: bool,
        full_text: str | None = None,
        max_chars: int | None = None,
    ) -> SummaryState:
        status = row["status"]
        if status == STATUS_GENERATING and is_stale_generating(row["updated_at"]):
            return SummaryState(
                status=STATUS_FAILED,
                provider=row["provider"],
                model=row["model"],
                prompt_version=row["prompt_version"],
                language=row["language"],
                generated_at=None,
                failure_type=FAILURE_INTERRUPTED,
            )
        if status == STATUS_SUCCESS:
            try:
                stored_chars = row["input_chars"]
                stored_truncated = row["truncated"]
            except (IndexError, KeyError):
                stored_chars, stored_truncated = None, None
            if stored_chars is not None:
                input_chars = int(stored_chars)
                truncated = bool(stored_truncated)
            elif full_text is not None:
                _, input_chars, truncated = self._scope(full_text, max_chars)
            else:
                input_chars, truncated = None, False
        else:
            input_chars, truncated = None, False
        return SummaryState(
            status=status,
            summary=row["summary_text"] if status == STATUS_SUCCESS else None,
            provider=row["provider"],
            model=row["model"],
            prompt_version=row["prompt_version"],
            language=row["language"],
            generated_at=row["updated_at"] if status == STATUS_SUCCESS else None,
            failure_type=row["failure_type"] if status == STATUS_FAILED else None,
            cached=cached,
            input_chars=input_chars,
            truncated=truncated,
        )

    def _not_generated(self, identity: CacheIdentity) -> SummaryState:
        return SummaryState(
            status=STATUS_NOT_GENERATED,
            provider=identity.provider,
            model=identity.model,
            prompt_version=identity.prompt_version,
            language=identity.language,
        )

    async def get_summary(self, entry_ref: str) -> SummaryState:
        """Read-only state: NEVER calls the provider."""
        normalized, identity = await self._resolve(entry_ref)
        row = await self._fetch_row(identity)
        if row is None:
            return self._not_generated(identity)
        return self._state_from_row(row, cached=True)

    async def generate_summary(
        self, entry_ref: str, max_chars: int | None = None
    ) -> SummaryState:
        """Explicit generation: provider call only on a cache miss.

        F025：max_chars（512–50000）限定实际发送给 Provider 的正文范围
        （诚实截断，绝不估算 token）；None = 现行为（12000 上界的全文）。
        """
        normalized, identity = await self._resolve(entry_ref)
        row = await self._fetch_row(identity)
        if row is not None and row["status"] == STATUS_SUCCESS:
            return self._state_from_row(
                row, cached=True, full_text=normalized, max_chars=max_chars
            )
        async with self._lock_for(identity):
            row = await self._fetch_row(identity)
            if row is not None and row["status"] == STATUS_SUCCESS:
                return self._state_from_row(
                    row, cached=True, full_text=normalized, max_chars=max_chars
                )
            return await self._generate(normalized, identity, max_chars)

    @staticmethod
    def _scope(normalized: str, max_chars: int | None) -> tuple[str, int, bool]:
        """(effective_text, input_chars, truncated)；截断永远诚实。"""
        effective = normalized[:max_chars] if max_chars else normalized
        return effective, len(effective), len(effective) < len(normalized)

    def _lock_for(self, identity: AiCacheIdentity) -> asyncio.Lock:
        return self._locks.lock_for(identity.row_params())

    async def _generate(
        self,
        normalized: str,
        identity: CacheIdentity,
        max_chars: int | None = None,
    ) -> SummaryState:
        await self._db.migrate()
        settings = await self._settings.load()
        require_ai_configured(settings)
        await self._db.execute(
            "INSERT INTO ai_summaries (entry_ref, content_hash, provider, model, "
            "prompt_version, language, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(entry_ref, content_hash, provider, model, prompt_version, language) "
            "DO UPDATE SET status = 'generating', failure_type = NULL, "
            "summary_text = NULL, updated_at = excluded.updated_at",
            (*identity.row_params(), STATUS_GENERATING, _utc_now(), _utc_now()),
        )
        effective, input_chars, truncated = self._scope(normalized, max_chars)
        provider = await self._provider_factory(
            settings[KEY_BASE_URL], settings[KEY_MODEL]
        )
        try:
            summary = await provider.summarize(
                text=effective, language=identity.language
            )
        except AiProviderError as exc:
            if isinstance(exc, AiNotConfigured):
                # No provider state to keep: remove the transient row so a
                # later GET honestly reports not_generated.
                await self._db.execute(
                    "DELETE FROM ai_summaries WHERE entry_ref = ? AND content_hash = ? "
                    "AND provider = ? AND model = ? AND prompt_version = ? AND language = ?",
                    identity.row_params(),
                )
            else:
                await self._db.execute(
                    "UPDATE ai_summaries SET status = 'failed', failure_type = ?, "
                    "summary_text = NULL, updated_at = ? "
                    "WHERE entry_ref = ? AND content_hash = ? AND provider = ? "
                    "AND model = ? AND prompt_version = ? AND language = ?",
                    (
                        _provider_failure_type(exc),
                        _utc_now(),
                        *identity.row_params(),
                    ),
                )
            raise
        await self._db.execute(
            "UPDATE ai_summaries SET status = 'success', summary_text = ?, "
            "failure_type = NULL, input_chars = ?, truncated = ?, updated_at = ? "
            "WHERE entry_ref = ? AND content_hash = ? AND provider = ? "
            "AND model = ? AND prompt_version = ? AND language = ?",
            (
                summary,
                input_chars,
                1 if truncated else 0,
                _utc_now(),
                *identity.row_params(),
            ),
        )
        # F027：成功生成才落一版（失败不产生新版本；重生成保留旧版）。
        from lumirss.ai_summary_versions import SummaryVersionStore

        await SummaryVersionStore(self._db).record_version(
            entry_ref=identity.entry_ref,
            content_hash=identity.content_hash,
            summary=summary,
            provider=identity.provider,
            model=identity.model,
        )
        row = await self._fetch_row(identity)
        assert row is not None  # just written
        return self._state_from_row(row, cached=False)
