"""F087 书签失效检查 —— 并发≤4 的有界探测，绝不改写书签 URL。

- 探测顺序：HEAD → 405/501/400 降级有界 GET（响应体读 ≤256KB 即断）；
  timeout 8s；SSRF 校验：生产走 pinned transport（复用 clip_fetch/
  ssrf_transport 层），测试注入 client_factory；
- 分类：ok | redirect | not_found | auth_required | rate_limited |
  timeout | network_error | blocked_ssrf；redirect 只报告 final_url，
  书签 URL 永不更新（负向断言依赖）；
- 并发≤4（信号量）、重复 ref 去重、取消传播（gather 正常取消）。

纯逻辑模块：无 SQL 写站点。
"""

import asyncio
import time
import urllib.parse
from typing import Any

import httpx

from lumirss.util import utc_now

_CHECK_TIMEOUT_S = 8.0
_MAX_BYTES = 256 * 1024
_CONCURRENCY = 4
_MAX_REDIRECTS = 5
_HEAD_FALLBACK_STATUSES = (400, 405, 501)


class SsrfBlocked(Exception):
    """目标解析到非公网地址 / 非法 scheme，映射 blocked_ssrf。"""


def _result(
    url: str,
    status: str,
    checked_at: str,
    *,
    http_status: int | None = None,
    final_url: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "ref": url,
        "status": status,
        "httpStatus": http_status,
        "finalUrl": final_url,
        "checkedAt": checked_at,
        "error": error,
    }


def _classify_status(code: int) -> str:
    if 200 <= code < 300:
        return "ok"
    if code in (401, 403):
        return "auth_required"
    if code in (404, 410):
        return "not_found"
    if code == 429:
        return "rate_limited"
    return "network_error"


class LinkCheckService:
    def __init__(
        self, *, client_factory: Any = None, timeout: float = _CHECK_TIMEOUT_S
    ) -> None:
        # 生产：SSRF-pinned AsyncClient 工厂；测试注入 MockTransport 工厂。
        self._client_factory = client_factory or _pinned_client_factory
        self._timeout = timeout
        self._semaphore = asyncio.Semaphore(_CONCURRENCY)

    async def check_one(self, url: str) -> dict[str, Any]:
        checked_at = utc_now()
        if not isinstance(url, str) or not url.lower().startswith(
            ("http://", "https://")
        ):
            return _result(url, "network_error", checked_at, error="invalid_url")
        async with self._semaphore:
            try:
                return await self._probe(url, checked_at)
            except asyncio.CancelledError:
                raise
            except SsrfBlocked:
                return _result(url, "blocked_ssrf", checked_at)
            except (TimeoutError, httpx.TimeoutException):
                return _result(url, "timeout", checked_at)
            except httpx.HTTPError as exc:
                return _result(
                    url, "network_error", checked_at, error=type(exc).__name__
                )

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        deadline: float,
    ) -> httpx.Response:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        return await asyncio.wait_for(
            client.request(method, url, follow_redirects=False),
            timeout=remaining,
        )

    async def _probe(self, url: str, checked_at: str) -> dict[str, Any]:
        deadline = time.monotonic() + self._timeout
        async with self._client_factory() as client:
            current = url
            redirects = 0
            for _hop in range(_MAX_REDIRECTS + 1):
                response = await self._request(client, "HEAD", current, deadline)
                if response.status_code in _HEAD_FALLBACK_STATUSES:
                    await response.aclose()
                    response = await self._request(
                        client, "GET", current, deadline
                    )
                    if response.status_code < 400:
                        # 有界读取：≤256KB 即断（大文件不整读）。
                        received = 0
                        async for chunk in response.aiter_bytes():
                            received += len(chunk)
                            if received >= _MAX_BYTES:
                                break
                    await response.aclose()
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    await response.aclose()
                    if not location:
                        return _result(
                            url,
                            "network_error",
                            checked_at,
                            error="no_location",
                        )
                    redirects += 1
                    if redirects > _MAX_REDIRECTS:
                        return _result(
                            url,
                            "network_error",
                            checked_at,
                            error="too_many_redirects",
                        )
                    current = urllib.parse.urljoin(current, location)
                    continue
                status = _classify_status(response.status_code)
                if redirects and status == "ok":
                    # 最终落在别处的 2xx：按「redirect」分类并报告 finalUrl。
                    status = "redirect"
                return _result(
                    url,
                    status,
                    checked_at,
                    http_status=response.status_code,
                    final_url=current if redirects else None,
                )
            return _result(url, "network_error", checked_at, error="loop")

    async def check_many(self, urls: list[str]) -> list[dict[str, Any]]:
        """去重 + 并发≤4；结果按输入首现顺序返回。"""
        ordered_urls = list(dict.fromkeys(urls))
        seen: dict[str, dict[str, Any]] = {}

        async def _one(u: str) -> None:
            seen[u] = await self.check_one(u)

        if ordered_urls:
            await asyncio.gather(*(_one(u) for u in ordered_urls))
        results: list[dict[str, Any]] = []
        for u in ordered_urls:
            item = dict(seen[u])
            item["ref"] = u
            results.append(item)
        return results


def _pinned_client_factory() -> Any:
    """生产客户端工厂：预检 + pinned dial（SSRF 校验在 dial 层强制）。"""
    from lumirss.feed_preview import _default_resolver, ensure_public_address
    from lumirss.ssrf_transport import PinnedAddressTransport

    def _ensure_public_or_block(address: Any) -> None:
        from lumirss.feed_preview import UnsafeFeedUrl

        try:
            ensure_public_address(address)
        except (ValueError, UnsafeFeedUrl) as exc:
            raise SsrfBlocked(str(exc)) from exc

    class _PinnedClient(httpx.AsyncClient):
        def __init__(self) -> None:
            transport = PinnedAddressTransport(
                resolver=_default_resolver,
                ensure_public=_ensure_public_or_block,
            )
            super().__init__(
                transport=transport, trust_env=False, follow_redirects=False
            )

    return _PinnedClient
