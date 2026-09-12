"""Snapshot job pipeline (phase2 M2, recovery P0-04): monolith, serial.

Monolith (CC0, external CLI) renders a self-contained single-file
snapshot of a page. Hard resource envelope (evidence in
docs/research/phase2/02-web-snapshots.md §14): one snapshot at a time
(asyncio lock), 90s wall clock, 50MB artifact cap, output in a
controlled temp path, best-effort partial cleanup on any failure.

SSRF (recovery P0-04): the top-level URL passes clip validation before
the child process exists, and — the actual fix — EVERY request monolith
makes (page, sub-resources, redirect hops, CONNECT tunnels) goes through
the in-process ``SsrfFilteringProxy`` (ssrf_proxy.py), which resolves,
policy-checks and dials the pinned address itself. monolith 2.10.1 was
verified empirically to honor HTTP_PROXY/HTTPS_PROXY/ALL_PROXY for all
of its fetches; the child gets a minimal env (PATH + proxy vars only —
never the server's full environment).

Binary pin (verified locally against the release artifacts):

- version: monolith 2.10.1 (GitHub release v2.10.1)
- sha256(monolith-gnu-linux-x86_64) =
  663ca914b078e91d5a854b4a07e913c613bbbcfe8fb11a24da1a6ab23c9205df
- sha256(monolith-gnu-linux-aarch64) =
  7f8cac6291b4015b24b964fcdf115a196abecc59e9149f7aa485175943f99997
- argv verified against the real ``monolith --help`` of that build:
  ``monolith <url> -o <out> -t 60 -I -j`` — ``-o`` output file (the old
  code passed the path as a second positional and abused ``-C``, the
  COOKIE-FILE flag), ``-t`` per-request network timeout, ``-I`` isolate
  the document, ``-j`` remove JavaScript. No ``-e/--ignore-errors``:
  network failures are fatal → honest errors, never partial fake saves.
  No cookies are ever attached (``-C`` is never passed).

Monolith missing → honest 503, never a fake success.
"""

import asyncio
import os
import shutil
import tempfile
from pathlib import Path

from lumirss.clip_fetch import validate_clip_url, validate_hop
from lumirss.library_assets import (
    _MAX_SNAPSHOT_BYTES,
    AssetStore,
)
from lumirss.ssrf_proxy import SsrfFilteringProxy
from lumirss.util import utc_now

MONOLITH_PIN_VERSION = "2.10.1"
_MONOLITH_WALL_CLOCK_SECONDS = 90
_MONOLITH_NETWORK_TIMEOUT = "60"  # -t: per-request, seconds

_CHILD_ENV = {
    "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    "HTTP_PROXY": "",
    "HTTPS_PROXY": "",
    "ALL_PROXY": "",
    "http_proxy": "",
    "https_proxy": "",
    "all_proxy": "",
    "NO_PROXY": "",
}


class MonolithUnavailable(Exception):
    """The monolith binary is not installed on the host."""


class SnapshotFailed(Exception):
    """monolith ran and failed (non-zero exit, empty output, timeout)."""


def monolith_path() -> str | None:
    return shutil.which("monolith")


def child_env(proxy_url: str) -> dict[str, str]:
    """Minimal env for the child: PATH + proxy pointers, nothing else."""
    env = dict(_CHILD_ENV)
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env[key] = proxy_url
    return env


class SnapshotJobRunner:
    """Serial monolith execution feeding the AssetStore."""

    def __init__(
        self,
        assets: AssetStore,
        *,
        proxy_factory=SsrfFilteringProxy,
    ) -> None:
        self._assets = assets
        self._lock = asyncio.Lock()
        self._proxy_factory = proxy_factory

    async def run(self, url: str) -> dict:
        """Capture ``url`` and store the artifact. Returns asset + meta."""
        validate_clip_url(url)
        # Cheap pre-flight BEFORE any child process exists; the proxy
        # enforces the same policy on every request monolith makes.
        await validate_hop(url)
        binary = monolith_path()
        if binary is None:
            raise MonolithUnavailable(
                "快照工具 monolith 未安装在服务器上，快照功能不可用。"
            )
        async with self._lock:
            async with self._proxy_factory() as proxy:
                data = await self._capture(binary, url, proxy)
            record, deduped = await self._assets.save_snapshot(
                data=data, mime="text/html", url=url
            )
            return {
                "asset": record.to_dict(),
                "deduplicated": deduped,
                "capturedAt": utc_now(),
                "url": url,
            }

    async def _capture(self, binary: str, url: str, proxy) -> bytes:
        with tempfile.TemporaryDirectory(prefix="lumirss-snap-") as tmp:
            out_path = Path(tmp) / "page.html"
            try:
                process = await asyncio.create_subprocess_exec(
                    binary,
                    url,
                    "-o",
                    str(out_path),
                    "-t",
                    _MONOLITH_NETWORK_TIMEOUT,
                    "-I",
                    "-j",
                    env=child_env(proxy.url),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except OSError as exc:
                raise MonolithUnavailable("快照工具 monolith 无法启动。") from exc
            try:
                _stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=_MONOLITH_WALL_CLOCK_SECONDS,
                )
            except TimeoutError:
                process.kill()
                raise SnapshotFailed(
                    f"快照生成超时（{_MONOLITH_WALL_CLOCK_SECONDS}s）。"
                ) from None
            if process.returncode != 0 or not out_path.is_file():
                detail = stderr.decode("utf-8", errors="replace")[:200]
                raise SnapshotFailed(
                    f"快照生成失败（exit {process.returncode}）：{detail or '无输出'}"
                )
            data = out_path.read_bytes()
            if not data:
                raise SnapshotFailed("快照生成失败：输出为空。")
            if len(data) > _MAX_SNAPSHOT_BYTES:
                raise SnapshotFailed("快照超过 50MB 上限。")
        return data
