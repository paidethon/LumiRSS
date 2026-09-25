"""N098 音频生成缓存 —— 服务端 TTS 合成 + per-user 缓存（LRU 50MB）。

面向「用户自配的 OpenAI 兼容 TTS profile」（purpose=tts，经既有
profile 系统解析 base_url/model/key）：POST {base}/audio/speech。
缓存键 = (sha256(text), voice, model)：命中绝不发外部请求（诚实口径
由响应头 X-Cache: hit|miss 承载）；未命中调一次 provider 并缓存。

诚实边界：
- 只在用户配置了 TTS 能力（base_url+model+key 齐全）时可用；未配置
  → TtsNotConfigured（映射 409），UI 必须如实说明，绝不假装能合成；
- 单条音频 ≤5MB（更大直接拒绝并说明——不缓存截断的半截音频）；
- 总量 50MB LRU：超出按 last_used_at 最旧先删（命中会推进 LRU 位
  次，created_at 保持创建时间不被命中改写）；
- per-user 库：缓存物理隔离，跨用户永不可见。
"""

import hashlib
import uuid as _uuid
from dataclasses import dataclass
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

MAX_TEXT_CHARS = 2000
MAX_AUDIO_BYTES = 5 * 1024 * 1024  # 5MB 单条上限
TOTAL_CACHE_BYTES = 50 * 1024 * 1024  # 50MB 总量 LRU
DEFAULT_VOICE = "alloy"
# OpenAI /audio/speech 的既知声音（OpenAI 兼容端点普遍沿用；非穷举——
# 自建兼容端点可能自定义，校验只拒空白）。
TTS_TIMEOUT_S = 60.0


class TtsError(Exception):
    """TTS 合成失败基类（message 浏览器安全）。"""


class TtsNotConfigured(TtsError):
    """用户没有配置 TTS 能力的 provider（purpose=tts 无有效密钥）。"""


class TtsTextInvalid(TtsError):
    """text/voice 负载非法（映射 422）。"""


class TtsUpstreamError(TtsError):
    """provider 调用失败（状态码/网络；绝不回传上游响应体）。"""


def text_hash_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TtsProviderConfig:
    """已解析的 TTS provider 配置（server-side only，key 绝不序列化）。"""

    base_url: str
    model: str
    api_key: str

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model and self.api_key)


class TtsCacheStore:
    """tts_cache 表的全部 SQL（inline literal + 绑定参数）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, *, text_hash: str, voice: str, model: str) -> bytes | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, audio FROM tts_cache WHERE text_hash = ? AND voice = ? AND model = ?",
            (text_hash, voice, model),
        )
        if row is None:
            return None
        # 命中推进 LRU 位次（created_at 保持创建时间，列表展示不撒谎）。
        await self._db.execute(
            "UPDATE tts_cache SET last_used_at = ? WHERE id = ?",
            (utc_now(), str(row["id"])),
        )
        return bytes(row["audio"] or b"")

    async def put(
        self, *, text_hash: str, voice: str, model: str, audio: bytes
    ) -> dict[str, Any]:
        now = utc_now()
        entry_id = str(_uuid.uuid4())
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO tts_cache (id, text_hash, voice, model, audio, size_bytes, created_at, last_used_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (entry_id, text_hash, voice, model, audio, len(audio), now, now),
        )
        await self._trim_lru()
        return {
            "id": entry_id,
            "textHash": text_hash,
            "voice": voice,
            "model": model,
            "sizeBytes": len(audio),
            "createdAt": now,
        }

    async def _trim_lru(self) -> int:
        """总量 ≤TOTAL_CACHE_BYTES：最旧 last_used_at 先删。返回删除数。"""
        row = await self._db.fetch_one("SELECT COALESCE(SUM(size_bytes), 0) AS total FROM tts_cache")
        total = int(row["total"]) if row is not None else 0
        removed = 0
        while total > TOTAL_CACHE_BYTES:
            oldest = await self._db.fetch_one(
                "SELECT id, size_bytes FROM tts_cache ORDER BY last_used_at ASC, rowid ASC LIMIT 1"
            )
            if oldest is None:
                break
            await self._db.execute("DELETE FROM tts_cache WHERE id = ?", (str(oldest["id"]),))
            total -= int(oldest["size_bytes"] or 0)
            removed += 1
        return removed

    async def list_entries(self, *, limit: int = 200) -> dict[str, Any]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, text_hash, voice, model, size_bytes, created_at FROM tts_cache ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        )
        total_row = await self._db.fetch_one(
            "SELECT COALESCE(SUM(size_bytes), 0) AS total, COUNT(*) AS count FROM tts_cache"
        )
        return {
            "items": [
                {
                    "id": str(row["id"]),
                    "textHash": str(row["text_hash"]),
                    "voice": str(row["voice"]),
                    "model": str(row["model"]),
                    "sizeBytes": int(row["size_bytes"]),
                    "createdAt": str(row["created_at"]),
                }
                for row in rows
            ],
            "totalBytes": int(total_row["total"]) if total_row is not None else 0,
            "count": int(total_row["count"]) if total_row is not None else 0,
            "capBytes": TOTAL_CACHE_BYTES,
        }

    async def delete_one(self, entry_id: str) -> bool:
        await self._db.migrate()
        changed = await self._db.execute("DELETE FROM tts_cache WHERE id = ?", (entry_id,))
        return bool(changed)

    async def delete_all(self) -> int:
        """清空本人全部缓存（per-user 库：只可能是本人的行）。"""
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT COUNT(*) AS n FROM tts_cache")
        await self._db.execute("DELETE FROM tts_cache")
        return int(row["n"]) if row is not None else 0


async def synthesize(
    db: Database,
    http: Any,
    config: TtsProviderConfig,
    *,
    text: str,
    voice: str = DEFAULT_VOICE,
) -> tuple[bytes, bool]:
    """合成一段语音（≤2000 字符），缓存优先。返回 (audio, cache_hit)。

    缓存命中 → 零外部请求；未命中 → 恰好一次 provider 调用并落缓存。
    """
    clean = str(text or "").strip()
    if not clean:
        raise TtsTextInvalid("text 不能为空。")
    if len(clean) > MAX_TEXT_CHARS:
        raise TtsTextInvalid(f"text 过长（≤{MAX_TEXT_CHARS} 字符）。")
    clean_voice = str(voice or DEFAULT_VOICE).strip() or DEFAULT_VOICE
    if len(clean_voice) > 100:
        raise TtsTextInvalid("voice 非法。")
    if not config.configured:
        raise TtsNotConfigured("未配置 TTS provider（AI 设置中为 TTS 用途选择已启用的 profile）。")

    store = TtsCacheStore(db)
    digest = text_hash_of(clean)
    cached = await store.get(text_hash=digest, voice=clean_voice, model=config.model)
    if cached is not None:
        return cached, True

    audio = await _call_provider(http, config, text=clean, voice=clean_voice)
    if len(audio) > MAX_AUDIO_BYTES:
        raise TtsUpstreamError("provider 返回的音频超过 5MB 单条上限，未缓存。")
    await store.put(text_hash=digest, voice=clean_voice, model=config.model, audio=audio)
    return audio, False


async def _call_provider(
    http: Any, config: TtsProviderConfig, *, text: str, voice: str
) -> bytes:
    """OpenAI 兼容 /audio/speech 调用（恰好一次；错误分型稳定）。"""
    base = config.base_url.rstrip("/")
    url = f"{base}/audio/speech"
    try:
        response = await http.post(
            url,
            json={
                "model": config.model,
                "input": text,
                "voice": voice,
                "response_format": "mp3",
            },
            headers={"Authorization": f"Bearer {config.api_key}"},
            timeout=TTS_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001 — 网络/超时统一上游错误
        raise TtsUpstreamError(f"TTS provider 调用失败：{type(exc).__name__}") from exc
    if response.status_code != 200:
        raise TtsUpstreamError(f"TTS provider 返回 {response.status_code}。")
    return response.content or b""
