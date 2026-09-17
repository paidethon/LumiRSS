"""F23 列表标题按需翻译 —— 单条显式请求 + 缓存。

验收语义：
- 只对用户明确请求的单条标题翻译（一次一条，无批量入口 → 不会滚动
  一次就全库收费）；
- 缓存身份 = (标题内容哈希, 目标语言, 模型, prompt_version)——标题
  变化、语言切换或模型更换自然失效；
- 原题永远保留（返回 originalTitle + translatedTitle，由 UI 叠加展示）；
- 失败/取消明确：provider 错误映射到稳定 Ai* 异常族，绝不假成功。
"""

import hashlib
from typing import Any

from lumirss.ai_artifacts import content_hash, normalize_ai_content
from lumirss.ai_provider import AiInvalidResponse, AiProviderError
from lumirss.storage import Database
from lumirss.util import utc_now

_TITLE_PROMPT_VERSION = "title-translate-v1"
_MAX_TITLE_INPUT = 500
_MAX_TITLE_OUTPUT = 500
_LANGUAGES = ("zh-CN", "en")


def title_hash_of(title: str) -> str:
    normalized = normalize_ai_content(title)[:_MAX_TITLE_INPUT]
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class TitleTranslationService:
    """Cache-first single-title translation (no batch entry point)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def translate(
        self,
        adapter: Any,
        ai_settings: Any,
        provider_factory: Any,
        entry_ref: str,
        language: str,
    ) -> dict[str, Any]:
        """返回 {originalTitle, translatedTitle, cached, language, model}。

        显式语言参数缺席时回退 AI 设置里的翻译目标语言。"""
        from lumirss.ai_settings import KEY_TRANSLATION_LANGUAGE
        from lumirss.entryref import InvalidEntryReference, decode_entry_ref

        try:
            item_id = decode_entry_ref(entry_ref.removeprefix("rss:"))
        except InvalidEntryReference as exc:
            raise AiInvalidResponse("invalid entry reference.") from exc
        detail = await adapter.get_entry(item_id)
        original = normalize_ai_content(detail.title)[:_MAX_TITLE_INPUT]
        if not original.strip():
            raise AiInvalidResponse("This entry has no title to translate.")
        ai_values = await ai_settings.load()
        model = str(ai_values.get("ai.model") or "")
        if language not in _LANGUAGES:
            language = str(ai_values.get(KEY_TRANSLATION_LANGUAGE) or "zh-CN")
            if language not in _LANGUAGES:
                language = "zh-CN"
        t_hash = content_hash(original)
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT translated_title FROM title_translations WHERE title_hash = ? AND language = ? AND model = ? AND prompt_version = ?",
            (t_hash, language, model, _TITLE_PROMPT_VERSION),
        )
        if row is not None:
            return {
                "originalTitle": original,
                "translatedTitle": str(row["translated_title"]),
                "cached": True,
                "language": language,
                "model": model,
            }
        if not base_url_ok(ai_values):
            from lumirss.ai_provider import AiNotConfigured

            raise AiNotConfigured("AI 未配置。")
        provider = await provider_factory(str(ai_values.get("ai.base_url") or ""), model)
        system = (
            f"Translate the article title into {language}. Keep proper nouns, "
            "product names and numbers as-is. Output ONLY the translated "
            "title: no quotes, no explanation, no original text."
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": original},
        ]
        try:
            translated = (await provider.complete(messages=messages)).strip()
        except AiProviderError:
            raise
        if not translated or len(translated) > _MAX_TITLE_OUTPUT:
            raise AiInvalidResponse("Translation output is empty or too long.")
        now = utc_now()
        await self._db.execute(
            "INSERT INTO title_translations (title_hash, language, model, prompt_version, original_title, translated_title, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(title_hash, language, model, prompt_version) DO UPDATE SET translated_title = excluded.translated_title, updated_at = excluded.updated_at",
            (
                t_hash,
                language,
                model,
                _TITLE_PROMPT_VERSION,
                original,
                translated,
                now,
                now,
            ),
        )
        return {
            "originalTitle": original,
            "translatedTitle": translated,
            "cached": False,
            "language": language,
            "model": model,
        }


def base_url_ok(ai_values: dict[str, Any]) -> bool:
    return bool(str(ai_values.get("ai.base_url") or "").strip()) and bool(
        str(ai_values.get("ai.model") or "").strip()
    )
