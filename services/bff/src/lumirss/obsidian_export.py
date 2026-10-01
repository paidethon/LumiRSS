"""R07 服务端受限写入 —— 把 Lumi 内容导出为 Obsidian 仓库内的 Markdown。

与 ADR-0004 只读投影（:mod:`lumirss.obsidian`）的关系：

- 读面对 ``/vault``（只读挂载）绝不写——那里一个写调用都不存在；
- 本模块的写面只落「导出根」：部署上独立挂载的服务端可写目录
  （容器内路径 ``LUMIRSS_OBSIDIAN_EXPORT_DIR``，生产 overlay 挂
  ``/vault-export``，rw；通常指向 vault 内一个 Lumi 专用子树），
  且只在 ``<root>/<subdir>/<user_id>/`` 下创建文件。``subdir`` 是
  用户级偏好（obsidian_export_prefs，默认 ``LumiRSS``），``user_id``
  是服务端派生的账户 id——同一实例的多个账户互不见对方的导出。

硬保证（风格与 obsidian.py 对齐）：

- containment：导出根 realpath 化一次；每次写前把目标目录与目标
  文件名重新 resolve 并拒绝越出根——子目录里埋的 symlink/junction
  指向外部 = 拒绝，绝不跟进；
- never overwrite：写入走「tmp + ``os.link``」——``os.link`` 对已
  存在目标原子失败，因此已存在文件（包括用户手写的同名笔记）在
  文件系统层面不可能被覆盖；文件系统不支持硬链接时退化为
  ``O_EXCL`` 直写（依旧绝不覆盖，仅放弃原子性，注释如实声明）；
- 幂等：content-id 由 ItemRef 确定性派生；重复导出同 content-id 且
  内容 hash 相同 → 直接返回已存在（written=False），不重复写；
- 冲突：同名不同内容 → ``-2`` … ``-99`` 后缀的新文件名，旧文件
  原样保留；
- bounded：单文件 1MB、单次批 50 条、每日写入 64MB（按 obsidian.py
  的有界风格取整）；正文超限截断且 frontmatter 如实标记
  ``truncated: true``；
- 台账：每次 written/exists 落一行 obsidian_export_log（per-user
  库）——「今日用量 / 最近导出 / 每日上限」都从这张表推导。文件
  本体永远以文件系统为准，台账只是审计投影。

本模块不做内容收集（需要 request 级服务：adapter / 各 store）——
收集在 routers/obsidian_export.py 完成；这里是纯文件系统 + 渲染 +
台账，直接可测。
"""

import contextlib
import hashlib
import os
import re
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

# ---- 有界常量（与只读投影 obsidian.py 同风格） -------------------------

_MAX_FILE_BYTES = 1024 * 1024  # 单个导出文件 1MB（与投影扫描上限一致）
_MAX_BATCH_REFS = 50  # 单次请求最多导出条数
_MAX_DAILY_BYTES = 64 * 1024 * 1024  # 每用户每日写入容量上限
_MAX_BODY_CHARS = 200_000  # 正文字符上限（超出截断 + truncated 标记）
_MAX_SUMMARY_CHARS = 8_000
_MAX_ANNOTATION_CHARS = 4_000
_MAX_ANNOTATIONS = 100
_MAX_TAGS = 12
_MAX_TAG_LENGTH = 50
_MAX_TITLE_LENGTH = 500
_MAX_FILENAME_STEM = 80
_MAX_SUBDIR_LENGTH = 200
_MAX_SUBDIR_DEPTH = 4
_SUFFIX_LIMIT = 99  # 同名冲突后缀 -2..-99，之后诚实失败

DEFAULT_EXPORT_SUBDIR = "LumiRSS"

_FILENAME_UNSAFE_RE = re.compile(r"[\\/:*?\"<>|]")
_SUBDIR_UNSAFE_RE = re.compile(r"[\x00-\x1f]")


class ExportNotConfigured(Exception):
    """导出根未配置（LUMIRSS_OBSIDIAN_EXPORT_DIR 为空）或不可达。"""


class ExportSubdirInvalid(Exception):
    """导出子目录设置未通过校验（.. / 绝对路径 / 反斜杠 / 过长）。"""


class ExportPathInvalid(Exception):
    """目标路径越出导出根（穿越 / symlink 逃逸）——拒绝，绝不跟进。"""


class ExportBatchTooLarge(Exception):
    """单次导出批量超过上限。"""


class ExportWriteFailed(Exception):
    """文件写入失败（权限 / 磁盘 / 文件系统限制）。"""


@dataclass(frozen=True)
class ExportPayload:
    """一条待导出内容（由路由层从各内容域收集，本模块只消费）。

    ``body_text`` 为 ``None`` = 无正文（如纯链接书签）→ 正文只写
    链接 + 元数据，并注明「未抓取全文」；绝不臆造正文。
    """

    ref: str
    source_type: str  # rss | bookmark | clip | snapshot | api_source | …
    title: str
    source_name: str
    url: str
    author: str | None = None
    published: str | None = None  # 发布时间（缺失则诚实省略）
    body_text: str | None = None
    tags: tuple[str, ...] = ()
    summary: str | None = None
    translation_title: str | None = None
    translation_text: str | None = None
    annotations: tuple[dict[str, str], ...] = field(default_factory=tuple)


def content_id_for(ref: str) -> str:
    """ItemRef → 稳定 content-id（16 hex）。

    同一 ItemRef 永远得到同一 content-id：文件名可预测、重复导出可
    判等。加上域分隔前缀避免 ``rss:e1.x`` 与 ``library:e1.x`` 之类
    前缀歧义。
    """
    digest = hashlib.sha256(f"lumirss-export-v1:{ref}".encode())
    return digest.hexdigest()[:16]


def slug_stem(title: str, content_id: str) -> str:
    """标题 → 文件名安全 stem，追加 content-id 前 8 位保证确定性。"""
    stem = _FILENAME_UNSAFE_RE.sub("-", str(title or "").strip())
    stem = re.sub(r"\s+", " ", stem).strip("- .")
    stem = stem[:_MAX_FILENAME_STEM].strip("- .")
    return f"{stem or '内容'}-{content_id[:8]}"


def normalize_export_subdir(value: str | None) -> str | None:
    """用户级导出子目录 → 合法相对子路径；非法输入返回 None。

    拒绝：绝对路径、反斜杠、控制字符、``.``/``..`` 段、以点开头的
    隐藏段、空段、超过 4 层或总长超限。合法 = ``a/b`` 形式的相对
    子路径（写进导出根之前还要过 containment 兜底）。
    """
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.startswith("/") or raw.startswith("\\"):
        return None  # 绝对路径 = 明确拒绝（不做静默改写）
    raw = raw.strip("/")
    if not raw:
        return None
    if "\\" in raw or _SUBDIR_UNSAFE_RE.search(raw):
        return None
    segments = raw.split("/")
    if len(segments) > _MAX_SUBDIR_DEPTH:
        return None
    clean: list[str] = []
    for segment in segments:
        segment = segment.strip()
        if (
            not segment
            or segment in (".", "..")
            or segment.startswith(".")
            or len(segment) > 80
        ):
            return None
        clean.append(segment)
    joined = "/".join(clean)
    if len(joined) > _MAX_SUBDIR_LENGTH:
        return None
    return joined


def validate_export_subdir(value: str | None) -> str:
    """读路径的宽容版本：非法 / 缺失输入回退默认（绝不抛给批量导出）。"""
    return normalize_export_subdir(value) or DEFAULT_EXPORT_SUBDIR


def canonical_export_root(raw: str) -> Path:
    """导出根 realpath 化；未配置 / 不存在 / 不是目录 → 诚实异常。"""
    if not raw or not raw.strip():
        raise ExportNotConfigured("未配置导出目录（LUMIRSS_OBSIDIAN_EXPORT_DIR）。")
    try:
        root = Path(raw.strip()).expanduser().resolve(strict=True)
    except FileNotFoundError as exc:
        raise ExportNotConfigured("导出目录不存在（挂载未就绪）。") from exc
    except OSError as exc:
        raise ExportNotConfigured("导出目录无法访问。") from exc
    if not root.is_dir():
        raise ExportNotConfigured("导出路径不是目录。")
    return root


def _contained(root: Path, candidate: Path) -> Path | None:
    """重新 resolve 并拒绝越出 root（symlink 逃逸等）；风格同 obsidian.py。"""
    try:
        resolved = candidate.resolve()
        if resolved == root or root in resolved.parents:
            return resolved
    except OSError:
        return None
    return None


def ensure_export_dir(root: Path, segments: list[str]) -> Path:
    """``root/<seg>/…`` 目录落地：mkdir 前后各做一次 containment 校验。

    mkdir 前的非严格 resolve 拦截已存在的 symlink 链；mkdir（对
    symlink-to-dir 是 no-op）之后的严格 resolve 兜底「mkdir 恰好落
    在外部 symlink 上」的竞态。返回严格化后的目录，后续写入都以它
    为基准。
    """
    target = root
    for segment in segments:
        target = target / segment
    if _contained(root, target) is None:
        raise ExportPathInvalid("导出目标越出导出根，已拒绝。")
    try:
        target.mkdir(parents=True, exist_ok=True)
        final = target.resolve(strict=True)
    except OSError as exc:
        raise ExportWriteFailed("导出目录无法创建。") from exc
    if final != root and root not in final.parents:
        raise ExportPathInvalid("导出目标越出导出根，已拒绝。")
    return final


def _yaml_str(value: str | None) -> str:
    """YAML 双引号标量（frontmatter 库可解析；反斜杠/引号/换行转义）。"""
    text = str(value or "")
    escaped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def render_note(payload: ExportPayload) -> dict[str, Any]:
    """Payload → 导出笔记。返回 {markdown, content_hash, stem, content_id}。

    frontmatter：标题、原始链接、来源类型、来源名称、作者/发布时间
    （存在才写）、导出时间、标签、稳定 content-id、原始 ItemRef、
    截断标记（仅截断时）。正文：正文（或「未抓取全文」）+ 可选
    AI 摘要 / 译文 / 批注分区（由请求 include 控制，收集端置入
    payload）。
    """
    content_id = content_id_for(payload.ref)
    body = str(payload.body_text or "").strip()
    truncated = False
    if len(body) > _MAX_BODY_CHARS:
        body = body[:_MAX_BODY_CHARS]
        truncated = True
    lines: list[str] = [
        "---",
        f"title: {_yaml_str(payload.title[:_MAX_TITLE_LENGTH] or '未命名')}",
    ]
    if payload.url:
        lines.append(f"url: {_yaml_str(payload.url)}")
    lines.append(f"source-type: {_yaml_str(payload.source_type)}")
    lines.append(f"source-name: {_yaml_str(payload.source_name)}")
    if payload.author and payload.author.strip():
        lines.append(f"author: {_yaml_str(payload.author.strip())}")
    if payload.published and payload.published.strip():
        lines.append(f"published: {_yaml_str(payload.published.strip())}")
    lines.append(f"exported: {_yaml_str(utc_now())}")
    tags: list[str] = ["lumirss", payload.source_type or "unknown"]
    for tag in payload.tags:
        clean = str(tag).strip().lstrip("#")[:_MAX_TAG_LENGTH]
        if clean and clean not in tags:
            tags.append(clean)
    lines.append("tags:")
    for tag in tags[:_MAX_TAGS]:
        lines.append(f"  - {_yaml_str(tag)}")
    lines.append(f"content-id: {content_id}")
    lines.append(f"lumirss-ref: {_yaml_str(payload.ref)}")
    if truncated:
        lines.append("truncated: true")
    lines.append("---")
    lines.append("")

    if body:
        lines.append(body)
        lines.append("")
    else:
        # 无正文书签：正文只写链接 + 元数据，并诚实注明未抓取全文。
        lines.extend(
            [
                "> [!warning] 未抓取全文",
                "> 该条目为链接收藏，LumiRSS 未抓取正文；全文请访问原始链接。",
            ]
        )
        if payload.url:
            lines.append(f"> 原始链接：{payload.url}")
        lines.append("")

    summary = str(payload.summary or "").strip()
    if summary:
        lines.extend(["## AI 摘要", "", summary[:_MAX_SUMMARY_CHARS], ""])
    translation = str(payload.translation_text or "").strip()
    if translation:
        title_line = str(payload.translation_title or "").strip()
        heading = f"## 译文：{title_line}" if title_line else "## 译文"
        lines.extend([heading, "", translation[:_MAX_SUMMARY_CHARS], ""])
    if payload.annotations:
        lines.append("## 批注")
        lines.append("")
        for annotation in payload.annotations[:_MAX_ANNOTATIONS]:
            quote = str(annotation.get("quote") or "").strip()[
                :_MAX_ANNOTATION_CHARS
            ]
            note = str(annotation.get("note") or "").strip()[
                :_MAX_ANNOTATION_CHARS
            ]
            link = str(annotation.get("link") or "").strip()
            if quote:
                lines.append(f"> {quote}")
            if note:
                lines.append(">")
                lines.append(f"> {note}")
            if link:
                lines.append(">")
                lines.append(f"> [→ LumiRSS 原文]({link})")
            lines.append("")
    markdown = "\n".join(lines).rstrip() + "\n"
    encoded = markdown.encode("utf-8")
    return {
        "markdown": markdown,
        "content_hash": hashlib.sha256(encoded).hexdigest(),
        "bytes": len(encoded),
        "stem": slug_stem(payload.title, content_id),
        "content_id": content_id,
    }


_SUFFIXES = [""] + [f"-{n}" for n in range(2, _SUFFIX_LIMIT + 1)]


def _atomic_create_no_clobber(directory: Path, name: str, content: bytes) -> str:
    """原子且绝不覆盖地创建 ``directory/name``。

    主路径：写 tmp + ``os.link``——目标已存在时 link 在文件系统层面
    原子失败，用户手写文件不可能被覆盖。退化路径（文件系统不支持
    硬链接）：``O_EXCL`` 直写——依旧绝不覆盖，仅放弃「读方不会看到
    半个文件」的原子性（诚实降级，导出文件没有并发读者）。
    """
    # 纵深防御：不信任调用方——先把 directory 规范化到真实路径，再
    # 校验 name 是裸文件名，最后证明落点仍在该目录之内。
    directory = Path(directory).resolve()
    if os.path.basename(name) != name or name in {".", ".."}:
        raise ExportWriteFailed("导出文件名非法。")
    target = directory / name
    if not target.is_relative_to(directory):
        raise ExportWriteFailed("导出目标越出导出根。")
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=".lumi-export-", suffix=".tmp", dir=directory
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(tmp_fd, "wb") as handle:
            handle.write(content)
        try:
            os.link(tmp, target)
            return "written"
        except FileExistsError:
            raise
        except OSError:
            # EXDEV / EPERM / ENOSYS 等：该文件系统不支持硬链接。
            with open(target, "xb") as final:
                final.write(content)
            return "written"
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


def write_note_bounded(
    directory: Path, stem: str, content: bytes, content_hash: str
) -> tuple[Path, str]:
    """在 directory 下落一个不覆盖任何既有文件的 .md。

    返回 (绝对路径, outcome)；outcome ∈ {"written", "exists"}。
    已存在同名文件：内容 hash 相同 → 幂等 exists；不同 → 试下一个
    ``-N`` 后缀（旧文件原样保留）。读既有文件做判等是只读的。
    """
    if len(content) > _MAX_FILE_BYTES:
        raise ExportWriteFailed("导出内容超过单文件 1MB 上限。")
    for suffix in _SUFFIXES:
        name = f"{stem}{suffix}.md"
        candidate = directory / name
        if candidate.exists():
            try:
                existing = candidate.read_bytes()
            except OSError:
                continue  # 不可读 = 视为被占用，试下一个后缀
            if hashlib.sha256(existing).hexdigest() == content_hash:
                return candidate, "exists"
            continue  # 同名不同内容 → 换后缀新文件名
        try:
            outcome = _atomic_create_no_clobber(directory, name, content)
        except FileExistsError:
            continue  # 并发写入者抢先；下一后缀继续
        except OSError as exc:
            raise ExportWriteFailed("导出文件写入失败。") from exc
        return candidate, outcome
    raise ExportWriteFailed("同名冲突过多，无法生成新文件名。")


class ObsidianExportService:
    """导出编排：偏好（子目录）+ 受限写入 + 每日配额 + 台账。"""

    def __init__(self, db: Database, export_dir: str = "") -> None:
        self._db = db
        self._export_dir = (export_dir or "").strip()

    # ---- 偏好（per-user 单行，同 obsidian_export_settings 惯例） --------

    async def get_subdir(self) -> str:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT export_subdir FROM obsidian_export_prefs WHERE id = 1"
        )
        stored = str(row["export_subdir"]) if row is not None else ""
        return validate_export_subdir(stored)

    async def set_subdir(self, value: str) -> str:
        validated = normalize_export_subdir(value)
        if validated is None:
            raise ExportSubdirInvalid(
                "子目录只能包含中文、字母、数字、空格、连字符与斜杠（1–4 层），"
                "不能以点开头或包含 ..。"
            )
        await self._db.migrate()
        await self._db.execute(
            "UPDATE obsidian_export_prefs SET export_subdir = ?, updated_at = ? WHERE id = 1",
            (validated, utc_now()),
        )
        return validated

    # ---- 导出 ------------------------------------------------------------

    async def export_batch(
        self, payloads: list[ExportPayload], *, user_id: str
    ) -> list[dict[str, Any]]:
        """逐条导出；返回与输入同序的逐项结果（written|exists|failed）。

        单条失败绝不中断整批（风格同投影扫描的单文件降级）：越界、
        配额、写入失败都折进该项的 failed+原因。
        """
        if len(payloads) > _MAX_BATCH_REFS:
            raise ExportBatchTooLarge(f"单次最多导出 {_MAX_BATCH_REFS} 条。")
        try:
            root = canonical_export_root(self._export_dir)
        except ExportNotConfigured:
            return [
                self._failed(payload.ref, "export_unconfigured", "导出目录未配置或不可达。")
                for payload in payloads
            ]
        subdir = await self.get_subdir()
        # per-user 隔离：subdir 内再按服务端账户 id 分目录——多账户各自
        # 的导出互不混放；user_id 由中间件派生（alnum，见 user_scope）。
        safe_user = str(user_id)
        if not safe_user.isalnum() or len(safe_user) > 40:
            raise ExportPathInvalid("账户标识不合法，已拒绝。")
        try:
            directory = ensure_export_dir(root, [subdir, safe_user])
        except (ExportPathInvalid, ExportWriteFailed) as exc:
            return [
                self._failed(payload.ref, "export_path_rejected", str(exc))
                for payload in payloads
            ]
        today = utc_now()[:10]
        used = await self._written_bytes_since(today)
        results: list[dict[str, Any]] = []
        for payload in payloads:
            try:
                rendered = render_note(payload)
            except Exception:  # noqa: BLE001 — 单条渲染失败不拖垮整批
                results.append(
                    self._failed(payload.ref, "render_failed", "导出内容渲染失败。")
                )
                continue
            if used + rendered["bytes"] > _MAX_DAILY_BYTES:
                results.append(
                    self._failed(
                        payload.ref,
                        "quota_exceeded",
                        "已达今日导出写入容量上限，明天再试或减少批量。",
                    )
                )
                continue
            try:
                path, outcome = write_note_bounded(
                    directory,
                    rendered["stem"],
                    rendered["markdown"].encode("utf-8"),
                    rendered["content_hash"],
                )
            except ExportWriteFailed as exc:
                results.append(self._failed(payload.ref, "write_failed", str(exc)))
                continue
            used += rendered["bytes"] if outcome == "written" else 0
            rel_path = path.relative_to(root).as_posix()
            await self._log(
                ref=payload.ref,
                content_id=rendered["content_id"],
                rel_path=rel_path,
                title=payload.title,
                bytes_=rendered["bytes"],
                content_hash=rendered["content_hash"],
                outcome=outcome,
            )
            results.append(
                {
                    "ref": payload.ref,
                    "status": outcome,
                    "path": rel_path,
                    "reason": None,
                    "contentId": rendered["content_id"],
                    "bytes": rendered["bytes"],
                }
            )
        return results

    # ---- 状态 ------------------------------------------------------------

    async def status(self, *, user_id: str) -> dict[str, Any]:
        configured = True
        export_root = self._export_dir
        try:
            canonical_export_root(self._export_dir)
        except ExportNotConfigured:
            configured = False
            export_root = self._export_dir
        today = utc_now()[:10]
        await self._db.migrate()
        subdir = await self.get_subdir()
        recent_rows = await self._db.fetch_all(
            "SELECT ref, title, rel_path, bytes, outcome, created_at FROM obsidian_export_log"
            " ORDER BY created_at DESC, id DESC LIMIT 20"
        )
        return {
            "configured": configured,
            "exportRoot": export_root,
            "subdir": subdir,
            "userDir": f"{subdir}/{user_id}",
            "todayBytes": await self._written_bytes_since(today),
            "dailyLimitBytes": _MAX_DAILY_BYTES,
            "recent": [
                {
                    "ref": str(row["ref"]),
                    "title": str(row["title"]),
                    "relPath": str(row["rel_path"]),
                    "bytes": int(row["bytes"]),
                    "outcome": str(row["outcome"]),
                    "createdAt": str(row["created_at"]),
                }
                for row in recent_rows
            ],
        }

    # ---- 内部 ------------------------------------------------------------

    async def _written_bytes_since(self, day_prefix: str) -> int:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT COALESCE(SUM(bytes), 0) AS total FROM obsidian_export_log"
            " WHERE outcome = 'written' AND created_at >= ?",
            (day_prefix,),
        )
        return int(row["total"]) if row is not None else 0

    async def _log(
        self,
        *,
        ref: str,
        content_id: str,
        rel_path: str,
        title: str,
        bytes_: int,
        content_hash: str,
        outcome: str,
    ) -> None:
        await self._db.execute(
            "INSERT INTO obsidian_export_log (id, ref, content_id, rel_path, title, bytes, content_hash, outcome, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                ref,
                content_id,
                rel_path,
                title[:_MAX_TITLE_LENGTH],
                int(bytes_),
                content_hash,
                outcome,
                utc_now(),
            ),
        )

    @staticmethod
    def _failed(ref: str, reason: str, message: str) -> dict[str, Any]:
        return {
            "ref": ref,
            "status": "failed",
            "path": None,
            "reason": reason,
            "contentId": None,
            "bytes": 0,
            "message": message,
        }
