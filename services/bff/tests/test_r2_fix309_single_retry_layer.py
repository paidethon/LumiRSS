"""FIX-309 — 服务端与前端只保留一个重试责任层，调用数量有上界。

既有事实（BASELINE_OK 守卫，无产品改动）：

- 服务端（BFF）：AI provider 每次 ``complete()`` / ``chat_completion()``
  恰好一次上游 POST——超时/连接错误/非 2xx 一律映射稳定错误族直接抛出，
  没有自动重试（模块头声明即契约）；段翻译每批一次 POST，失败按块写
  failed 行，绝不重发；
- 前端（Web）：TanStack Query 全局默认 4xx 永不重试、网络/5xx 最多
  2 次（main.tsx Q-P2-20），mutations 未配置默认重试（0 次）；AI 生成
  入口全部是显式 mutation / 显式队列派发——每次用户动作恰好一次请求。

若未来在任一侧加入自动重试，必须先废弃另一侧的责任，并让这里的
调用计数断言保持真实上界。
"""

import asyncio
from pathlib import Path

import httpx
import pytest

from lumirss.ai_provider import (
    AiRateLimited,
    AiUpstreamError,
    OpenAICompatibleProvider,
)

run = asyncio.run

SRC = Path(__file__).resolve().parents[1] / "src" / "lumirss"


def _counting_transport(status_code: int, calls: list[int]):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(status_code, json={"error": {"message": "upstream"}})

    return httpx.MockTransport(handler)


def _provider(calls: list[int], status_code: int) -> OpenAICompatibleProvider:
    client = httpx.AsyncClient(
        transport=_counting_transport(status_code, calls),
        base_url="https://ai.local/v1",
    )
    return OpenAICompatibleProvider(
        client,
        base_url="https://ai.local/v1",
        model="test-model",
        api_key="x" * 24,
    )


@pytest.mark.parametrize("status_code", [429, 500, 503])
def test_provider_complete_makes_exactly_one_upstream_call(status_code):
    """上游失败：恰好 1 次上游调用 + 稳定错误族（服务端零自动重试）。"""
    calls: list[int] = []
    provider = _provider(calls, status_code)

    async def scenario():
        with pytest.raises((AiRateLimited, AiUpstreamError)):
            await provider.complete(messages=[{"role": "user", "content": "hi"}])
        with pytest.raises((AiRateLimited, AiUpstreamError)):
            await provider.chat_completion(messages=[{"role": "user", "content": "hi"}])
        await provider._client.aclose()

    run(scenario())
    # complete + chat_completion = 两次用户级调用 → 恰好两次上游请求，
    # 没有任何退避重发放大（429 也不重试——重试责任在调用方显式决定）。
    assert len(calls) == 2


def test_provider_module_has_no_retry_constructs():
    """静态钉：ai_provider 不含重试循环/退避/tenacity 构造。"""
    text = (SRC / "ai_provider.py").read_text(encoding="utf-8")
    assert "tenacity" not in text
    assert "backoff" not in text.lower()
    assert "for attempt" not in text
    assert "max_retries" not in text
    assert "RETRY" not in text
