"""Snapshot job pipeline (phase2 M2): monolith subprocess, serial.

Monolith (CC0, external CLI) renders a truly self-contained single-file
snapshot of a page. Hard resource envelope (evidence in
docs/research/phase2/02-web-snapshots.md §14): one snapshot at a time
(asyncio lock), 90s wall clock, 50MB artifact cap, output in a
controlled temp path, best-effort partial cleanup on any failure. SSRF:
the target URL passes the same validation as clips before the child
process ever runs; monolith's own sub-resource fetches cannot be
individually intercepted — therefore snapshots are fail-closed on the
top-level URL validation (private/metadata addresses never reach
monolith) and the artifact is served from an isolated sandbox origin,
never Lumi's own. Monolith missing → honest 503, never a fake success.
"""

import asyncio
import shutil
import tempfile
from pathlib import Path

from lumirss.clip_fetch import validate_clip_url, validate_hop
from lumirss.library_assets import AssetStore
from lumirss.util import utc_now

_MONOLITH_TIMEOUT_SECONDS = 90
_SNAPSHOT_PROMPT = "1"  # best-effort, non-interactive


class MonolithUnavailable(Exception):
    """The monolith binary is not installed on the host."""


class SnapshotFailed(Exception):
    """monolith ran and failed (non-zero exit, empty output, timeout)."""


def monolith_path() -> str | None:
    return shutil.which("monolith")


class SnapshotJobRunner:
    """Serial monolith execution feeding the AssetStore."""

    def __init__(self, assets: AssetStore) -> None:
        self._assets = assets
        self._lock = asyncio.Lock()

    async def run(self, url: str) -> dict:
        """Capture ``url`` and store the artifact. Returns asset + meta."""
        validate_clip_url(url)
        # Full DNS-level SSRF check BEFORE the child process exists:
        # monolith's own sub-resource fetches can't be intercepted, so the
        # only honest guarantee is refusing non-public targets entirely.
        await validate_hop(url)
        binary = monolith_path()
        if binary is None:
            raise MonolithUnavailable(
                "快照工具 monolith 未安装在服务器上，快照功能不可用。"
            )
        async with self._lock:
            with tempfile.TemporaryDirectory(prefix="lumirss-snap-") as tmp:
                out_path = Path(tmp) / "page.html"
                try:
                    process = await asyncio.create_subprocess_exec(
                        binary,
                        url,
                        str(out_path),
                        "-t",
                        "60",
                        "-I",
                        "-C",
                        _SNAPSHOT_PROMPT,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                except OSError as exc:
                    raise MonolithUnavailable(
                        "快照工具 monolith 无法启动。"
                    ) from exc
                try:
                    _stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=_MONOLITH_TIMEOUT_SECONDS,
                    )
                except TimeoutError:
                    process.kill()
                    raise SnapshotFailed("快照生成超时（90s）。") from None
                if process.returncode != 0 or not out_path.is_file():
                    detail = stderr.decode("utf-8", errors="replace")[:200]
                    raise SnapshotFailed(
                        f"快照生成失败（exit {process.returncode}）：{detail or '无输出'}"
                    )
                data = out_path.read_bytes()
                if not data:
                    raise SnapshotFailed("快照生成失败：输出为空。")
            # tmp dir context exited; artifact bytes already read into memory
            record, deduped = await self._assets.save_snapshot(
                data=data, mime="text/html"
            )
            return {
                "asset": record.to_dict(),
                "deduplicated": deduped,
                "capturedAt": utc_now(),
                "url": url,
            }
