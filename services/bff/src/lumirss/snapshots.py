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
import html as _html
import os
import re
import shutil
import tempfile
from html.parser import HTMLParser
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


# ---------------------------------------------------------------------------
# FIX-328 — 快照活动内容剥离（存储 + 读出双边界）。
#
# monolith -j 只移除 JavaScript；表单/on* 事件属性/javascript: 链接等
# 活动内容仍可能留在采集产物里。快照 HTML 在持久化（runner.run 采集后
# 落盘前）与读出（page.html 端点）两处都过 :func:`strip_active_content`
# ——存储本身即为惰性，遗留/绕过存储层的字节在读出端也被剥离；CSP
# ``sandbox`` 响应头保持为第三层纵深防御。原始网页 URL 作为数据
# （library_assets.url）原样保留，原网页仍可从详情/列表单独打开。
# ---------------------------------------------------------------------------

# 连同子树一起丢弃的容器（活动/可执行/导航劫持面）。
_FIX328_DROP_WITH_CONTENT = frozenset(
    {
        "script", "iframe", "frame", "frameset", "object", "embed", "applet",
        "form", "button", "select", "option", "optgroup", "textarea",
        "datalist", "output", "template", "portal", "noscript", "noframes",
        "noembed", "xmp", "plaintext", "svg", "math",
    }
)

# 丢弃但不参与深度配对的 void 标签（base 劫持相对链接、meta refresh、
# input 表单控件——快照读出时 CSP 已断外链，存储层同样不留）。注意
# <link> 不丢弃：内联 data:text/css 样式表是 N124 资源模型的合法成分
# 且无活动内容语义（外链形态由读出端 CSP default-src 'none' 阻断）。
_FIX328_DROP_VOID = frozenset({"base", "meta", "input"})

# HTML void 标签：不产生配对的结束标签（skip 深度配对时豁免）。
_FIX328_VOID_HTML = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr", "frame",
    }
)

# 需要按协议白名单校验值的 URL 属性。src 族（monolith 会把字体/媒体/
# 图片统一内联为 data:）放行 data:；可点击导航族（href/action…）不放
# 行 data:（data:text/html 导航面），仅 http/https/mailto/相对地址。
_FIX328_URL_ATTRS = frozenset(
    {
        "href", "src", "xlink:href", "action", "formaction", "poster",
        "background", "dynsrc", "lowsrc",
    }
)
_FIX328_SRC_LIKE_ATTRS = frozenset({"src", "xlink:href"})

_FIX328_SCHEME_RE = re.compile(r"^([a-z][a-z0-9+.\-]*):", re.IGNORECASE)
_FIX328_ALLOWED_SCHEMES = frozenset({"http", "https", "mailto"})
_FIX328_SRC_ALLOWED_SCHEMES = frozenset({"http", "https", "mailto", "data"})


def _filter_snapshot_attr(
    tag: str, name: str, value: str | None
) -> str | None:
    """返回保留的属性值；None = 该属性必须移除。"""
    lowered = name.lower()
    if lowered.startswith("on") or lowered == "srcset":
        return None  # 事件处理器无条件拒绝
    if lowered not in _FIX328_URL_ATTRS:
        return value if value is not None else ""
    # <link> 的样式表内联（data:text/css，N124 资源模型合法成分）按
    # src 族处理；data: 无脚本执行语义，外链由读出端 CSP 阻断。
    if tag == "link":
        allowed = _FIX328_SRC_ALLOWED_SCHEMES
    elif lowered in _FIX328_SRC_LIKE_ATTRS:
        allowed = _FIX328_SRC_ALLOWED_SCHEMES
    else:
        allowed = _FIX328_ALLOWED_SCHEMES
    # 剥掉全部空白/控制字符后再判协议（挫败 java\tscript: 变体）。
    cleaned = "".join((value or "").split())
    match = _FIX328_SCHEME_RE.match(cleaned)
    if match is None:
        return cleaned  # 相对地址 / 纯锚点
    if match.group(1).lower() in allowed:
        return cleaned
    return None


class _InertStripper(HTMLParser):
    """线性 HTML 重写：丢活动容器、剥 on*/危险 URL 属性，其余保真。

    标准库实现、迭代序列化（对敌意输入不递归）；<style> 内容按 CDATA
    原文透传（实体化会破坏 CSS 选择器），CSS 本身不具活动内容语义，
    外链/脚本由丢弃规则与读出端 CSP 兜底。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._skip_depth = 0
        self._in_style = False

    def _emit(self, text: str) -> None:
        self._out.append(text)

    def handle_starttag(self, tag, attrs):  # noqa: D401 — parser callback
        lowered = tag.lower()
        if self._skip_depth > 0:
            if lowered not in _FIX328_VOID_HTML:
                self._skip_depth += 1
            return
        if lowered in _FIX328_DROP_WITH_CONTENT:
            if lowered not in _FIX328_VOID_HTML:
                self._skip_depth += 1
            return
        if lowered in _FIX328_DROP_VOID:
            return
        if lowered == "style":
            self._in_style = True
        parts = [f"<{lowered}"]
        for name, value in attrs:
            if not name:
                continue
            kept = _filter_snapshot_attr(lowered, name, value)
            if kept is None:
                continue
            if value is None:
                parts.append(f" {name.lower()}")
            else:
                parts.append(f' {name.lower()}="{_html.escape(kept, quote=True)}"')
        parts.append(">")
        self._emit("".join(parts))

    def handle_startendtag(self, tag, attrs):  # noqa: D401 — parser callback
        lowered = tag.lower()
        self.handle_starttag(lowered, attrs)
        if lowered not in _FIX328_VOID_HTML:
            self.handle_endtag(lowered)  # 非空自闭合 → 立即配对，避免 skip 深度错位

    def handle_endtag(self, tag):  # noqa: D401 — parser callback
        lowered = tag.lower()
        if lowered == "style":
            self._in_style = False
        if self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if lowered in _FIX328_DROP_WITH_CONTENT or lowered in _FIX328_DROP_VOID:
            return
        if lowered in _FIX328_VOID_HTML:
            return
        self._emit(f"</{lowered}>")

    def handle_data(self, data):  # noqa: D401 — parser callback
        if self._skip_depth > 0:
            return
        if self._in_style:
            self._emit(data)  # CSS 原文（CDATA），绝不实体化
            return
        self._emit(_html.escape(data, quote=False))

    def handle_comment(self, data):  # noqa: D401 — parser callback
        return  # 注释整体丢弃（条件注释等历史攻击面）

    def handle_decl(self, decl):  # noqa: D401 — parser callback
        if decl.strip().lower().startswith("doctype"):
            # decl 取自 <! 与 > 之间，构造上不可能携带新标签。
            self._emit(f"<!{decl}>")

    def handle_pi(self, data):  # noqa: D401 — parser callback
        return

    def unknown_decl(self, data):  # noqa: D401 — parser callback
        return

    def result(self) -> str:
        return "".join(self._out)


def strip_active_content(html_text: str) -> str:
    """FIX-328：剥离快照 HTML 的活动内容（脚本/表单/框架/嵌入/事件属
    性/javascript: 链接/base·meta·link），其余结构尽量保真。

    解析器彻底失败时返回已产出部分（绝不 500 采集管线）。"""
    stripper = _InertStripper()
    try:
        stripper.feed(html_text)
        stripper.close()
    except Exception:  # noqa: BLE001 — 惰性降级优于采集失败
        pass
    return stripper.result()


def make_snapshot_inert(data: bytes) -> bytes:
    """字节级入口：UTF-8 解码 → 活动内容剥离 → UTF-8 回编码。"""
    try:
        html_text = data.decode("utf-8")
    except UnicodeDecodeError:
        html_text = data.decode("utf-8", errors="replace")
    return strip_active_content(html_text).encode("utf-8")


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
            # FIX-328：存储前剥离活动内容——落盘的字节本身即为惰性
            # （无脚本/表单/事件属性/javascript: 链接），原始 URL 仍作为
            # 数据保存在 asset 行上。
            data = make_snapshot_inert(data)
            record, deduped = await self._assets.save_snapshot(
                data=data, mime="text/html", url=url
            )
            # F033/F034：资源状态（页面 ok + 子资源 skipped，有界去重）
            # 与原始字节随采集结果一并返回（版本文本提取由路由层做）。
            from lumirss.snapshot_versions import extract_resource_urls

            diagnostics = extract_resource_urls(
                data.decode("utf-8", errors="replace"), url
            )
            return {
                "asset": record.to_dict(),
                "deduplicated": deduped,
                "capturedAt": utc_now(),
                "url": url,
                "resources": diagnostics["resources"],
                "resourcesTruncated": diagnostics["truncated"],
                "_data": data,
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
