"""NEW-264 翻译服务能力比较 —— 用户选择的少量非敏感样本的对照运行。

用户显式提交 1..5 段样本（每段 ≤500 字符，非敏感由用户自判，系统
只做体量上限），对「已配置」的服务端翻译通道逐样本运行一次：

- ai 侧：配置了 baseUrl+model 才参与；经与生成路径同一的
  purpose-aware provider 工厂调用（简单直译 prompt）。

（自托管 LibreTranslate 侧已随 R21 移除；历史报告 JSON 里的
libretranslate 侧数据按原样回读，不再产生新行。）

逐样本记录 结果文本 / 耗时（monotonic 实测）/ 错误类型。探测是
ephemeral 的：绝不写 ai_translation_segments 缓存行，只把用户可见
的报告本体存入本模块台账（每人保留最近 PROBE_HISTORY_CAP 条）。

无已配置服务 → available=False + 诚实 reason（不臆造结果）。
绝不自动发送整库 —— 只有显式 POST 携带的样本会被发出。

全部 SQL 为内联字面量 + 绑定参数。
"""

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

from lumirss.ai_provider import AiProviderError
from lumirss.ai_settings import (
    KEY_BASE_URL,
    KEY_MODEL,
    KEY_TRANSLATION_LANGUAGE,
    TRANSLATION_ENGINE_AI,
)
from lumirss.util import utc_now

PROBE_MAX_SAMPLES = 5
PROBE_MAX_SAMPLE_CHARS = 500
PROBE_HISTORY_CAP = 20
PROBE_TIMEOUT_SECONDS = 20.0

_INSERT_SQL = """INSERT INTO translation_capability_probes
(id, samples_json, sides_json, available, reason, created_at)
VALUES (?, ?, ?, ?, ?, ?)"""

_LIST_SQL = """SELECT * FROM translation_capability_probes
ORDER BY created_at DESC, id DESC LIMIT ?"""

_PRUNE_SQL = """DELETE FROM translation_capability_probes WHERE id NOT IN (
SELECT id FROM translation_capability_probes
ORDER BY created_at DESC, id DESC LIMIT ?)"""


class ProbeInvalid(Exception):
    """探测请求非法（样本数量/长度越界）→ 422。"""


@dataclass(frozen=True)
class ProbeReport:
    id: str
    samples: list[str]
    sides: dict[str, Any]
    available: bool
    reason: str
    created_at: str


def _clean_samples(samples: list[str]) -> list[str]:
    clean: list[str] = []
    for raw in samples:
        text = str(raw or "").strip()
        if not text:
            raise ProbeInvalid("样本不能为空。")
        if len(text) > PROBE_MAX_SAMPLE_CHARS:
            raise ProbeInvalid(
                f"每段样本最长 {PROBE_MAX_SAMPLE_CHARS} 字符（非敏感小样本）。"
            )
        clean.append(text)
    if not 1 <= len(clean) <= PROBE_MAX_SAMPLES:
        raise ProbeInvalid(
            f"样本数量必须是 1..{PROBE_MAX_SAMPLES} 段。"
        )
    return clean


def _translation_prompt(sample: str, language: str) -> str:
    target = "简体中文 (zh-CN)" if language == "zh-CN" else "English (en)"
    return (
        f"Translate the following text into {target}. "
        "Return ONLY the translation.\n\n" + sample
    )


async def _probe_ai_side(
    provider_factory, settings: dict[str, str], samples: list[str]
) -> dict[str, Any]:
    """AI 侧逐样本探测；未配置 → configured=False（诚实跳过）。"""
    base_url = settings[KEY_BASE_URL]
    model = settings[KEY_MODEL]
    if not base_url or not model:
        return {"configured": False, "reason": "AI 未配置 baseUrl/model。"}
    language = settings.get(KEY_TRANSLATION_LANGUAGE, "en")
    side: dict[str, Any] = {"configured": True, "samples": []}
    factory_exc: Exception | None = None
    provider = None
    try:
        provider = await provider_factory(base_url, model)
    except Exception as exc:  # 工厂失败（如未带密钥）按逐样本 upstream 记录
        factory_exc = exc
    for index, sample in enumerate(samples):
        started = time.monotonic()
        if factory_exc is not None or provider is None:
            side["samples"].append(
                {
                    "index": index,
                    "ok": False,
                    "error": "upstream",
                    "elapsedMs": int((time.monotonic() - started) * 1000),
                }
            )
            continue
        try:
            raw = await provider.complete(
                messages=[{"role": "user", "content": _translation_prompt(sample, language)}]
            )
            side["samples"].append(
                {
                    "index": index,
                    "ok": True,
                    "text": str(raw or "").strip(),
                    "elapsedMs": int((time.monotonic() - started) * 1000),
                }
            )
        except AiProviderError as exc:
            from lumirss.ai_artifacts import provider_failure_type

            side["samples"].append(
                {
                    "index": index,
                    "ok": False,
                    "error": provider_failure_type(exc),
                    "elapsedMs": int((time.monotonic() - started) * 1000),
                }
            )
    return side


async def run_probe(
    db: Any,
    settings: dict[str, str],
    samples: list[str],
    provider_factory: Any,
) -> ProbeReport:
    """一次显式能力探测（用户样本 → 已配置侧逐样本结果）。"""
    await db.migrate()
    clean = _clean_samples(samples)
    sides: dict[str, Any] = {
        TRANSLATION_ENGINE_AI: await _probe_ai_side(
            provider_factory, settings, clean
        ),
    }
    available = any(side.get("configured") for side in sides.values())
    reason = "" if available else "没有已配置的服务端翻译服务，无法比较。"
    now = utc_now()
    probe_id = f"tcp-{uuid.uuid4().hex[:16]}"
    await db.execute(
        _INSERT_SQL,
        (
            probe_id,
            json.dumps(clean, ensure_ascii=False),
            json.dumps(sides, ensure_ascii=False),
            1 if available else 0,
            reason,
            now,
        ),
    )
    await db.execute(_PRUNE_SQL, (PROBE_HISTORY_CAP,))
    return ProbeReport(probe_id, clean, sides, available, reason, now)


def _view(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "samples": json.loads(str(row["samples_json"])),
        "sides": json.loads(str(row["sides_json"])),
        "available": bool(row["available"]),
        "reason": str(row["reason"] or ""),
        "createdAt": str(row["created_at"] or ""),
    }


async def get_probe(db: Any, probe_id: str) -> dict[str, Any] | None:
    await db.migrate()
    row = await db.fetch_one(
        "SELECT * FROM translation_capability_probes WHERE id = ?", (probe_id,)
    )
    return _view(row) if row is not None else None


async def list_probes(db: Any, limit: int = 10) -> list[dict[str, Any]]:
    """本人最近的能力探测报告（新→旧；per-user 库天然隔离）。"""
    await db.migrate()
    rows = await db.fetch_all(_LIST_SQL, (max(1, min(limit, PROBE_HISTORY_CAP)),))
    return [_view(row) for row in rows]
