"""FIX-249 解压炸弹边界 —— 解压后的体积必须在读取侧被封顶。

外部内容（订阅健康探测的 feed URL、用户自配 TTS provider 的音频响应）
若「先整读再校验」，一个 gzip 炸弹（极小压缩字节 → 巨大解压输出）就会
在 BFF 内存里无界展开。本套件用流式 gzip 炸弹传输层证明：

- 健康探测只解压 ≤4KB+一个交付块的输出就断（绝不整读）；
- 头部探测路径（405/501 → GET）一个解压字节都不读；
- TTS provider 响应在 5MB 上限处干净失败（TtsUpstreamError），
  且解压工作止于上限附近，BFF 不受影响。

传输层按块交付「压缩」字节并计数：修复前调用方会拉满整条流（计数 =
总量）；修复后计数停在边界附近。测试绝无真实网络。
"""

import asyncio
import gzip

import httpx
import pytest

from lumirss.routers.subscriptions import _probe_feed_url
from lumirss.tts_service import (
    TtsProviderConfig,
    TtsUpstreamError,
    _call_provider,
)

_BOMB_DECOMPRESSED = b"0" * (128 * 1024 * 1024)  # 128MB 全零 → ~126KB gzip


class _GzipBombTransport(httpx.AsyncBaseTransport):
    """把一段解压内容压成 gzip，按 ``chunk`` 块交付压缩字节并计数。

    ``head_status`` 模拟健康探测的 HEAD 应答；GET 一律返回炸弹流。计数
    反映调用方真正拉取的压缩量 —— 有界读取应远小于流总量。
    """

    def __init__(
        self,
        *,
        content_type: str,
        head_status: int = 200,
        chunk: int = 4096,
        decompressed: bytes = _BOMB_DECOMPRESSED,
    ) -> None:
        self._payload = gzip.compress(decompressed, compresslevel=9)
        self._content_type = content_type
        self._head_status = head_status
        self._chunk = chunk
        self.pulled = 0
        self.head_calls = 0
        self.get_calls = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            self.head_calls += 1
            return httpx.Response(
                self._head_status, headers={"content-type": self._content_type}
            )
        self.get_calls += 1

        async def compressed_stream():
            for start in range(0, len(self._payload), self._chunk):
                block = self._payload[start : start + self._chunk]
                self.pulled += len(block)
                yield block

        return httpx.Response(
            200,
            headers={
                "content-type": self._content_type,
                "content-encoding": "gzip",
            },
            content=compressed_stream(),
        )


def test_probe_body_head_stops_streaming_gzip_bomb():
    """探测的正文嗅探路径：text/html 触发 GET 前缀读取，解压输出须在
    4KB+一个交付块内封顶——修复前 ``raw.content`` 会拉满 128MB。"""
    transport = _GzipBombTransport(content_type="text/html")
    client = httpx.AsyncClient(transport=transport, trust_env=False)

    async def scenario():
        return await _probe_feed_url(
            "https://feed.example/f.xml", 8.0, http_client=client
        )

    result = asyncio.run(scenario())
    assert result["status"] in ("ok", "bad_content")
    assert transport.get_calls == 1
    total = len(transport._payload)
    # 有界读取：只消化整条压缩流的极小部分（首块即超 4KB 解压输出）。
    assert transport.pulled * 10 < total, (transport.pulled, total)


def test_probe_header_only_get_never_reads_bomb_body():
    """405/501 → 降级 GET 只取状态与响应头：content-type 命中 xml 直接
    判 ok，一个解压字节都不读。修复前该 GET 会把整颗炸弹缓冲进内存。"""
    transport = _GzipBombTransport(
        content_type="application/xml", head_status=405
    )
    client = httpx.AsyncClient(transport=transport, trust_env=False)

    async def scenario():
        return await _probe_feed_url(
            "https://feed.example/f.xml", 8.0, http_client=client
        )

    result = asyncio.run(scenario())
    assert result["status"] == "ok"
    assert transport.get_calls == 1
    assert transport.pulled == 0  # 响应体零读取


def test_tts_provider_audio_cap_fails_clean_on_gzip_bomb():
    """TTS：5MB 上限在读侧生效——解压工作止于上限附近并抛
    TtsUpstreamError，而不是先整读 128MB 再校验长度。"""
    transport = _GzipBombTransport(content_type="audio/mpeg")
    client = httpx.AsyncClient(transport=transport, trust_env=False)
    config = TtsProviderConfig(
        base_url="https://tts.example/v1", model="tts-1", api_key="sk-test"
    )

    async def scenario():
        return await _call_provider(
            client, config, text="朗读文本", voice="alloy"
        )

    with pytest.raises(TtsUpstreamError):
        asyncio.run(scenario())
    total = len(transport._payload)
    # 5MB 解压输出 ≈ 5KB 压缩字节 + 一个 4KB 交付块，远小于整颗炸弹。
    assert transport.pulled * 10 < total, (transport.pulled, total)
