"""N010 个人数据迁出/迁入向导 —— 在 F39 只读 JSON 之外的 zip 交付形态。

导出（GET /export/lumi-data.zip）：manifest.json + 每组件一个 JSON 文件。
新增组件（F39 未覆盖的）：
- sources：订阅来源投影（feedUrl/title/category——绝无凭据/token）；
- readingState：已读/收藏状态（按条目引用；有界采集，截断如实标注）。

导入：先 preview（上传 zip → 各组件计数 + 冲突=已存在跳过数），再
apply（{importId, components[]} → 逐组件合并：跳过已存在、只加新的；
readingState 只对「当前账号已存在的引用」生效——绝不虚构上游条目）。

诚实边界：绝不包含秘密（AI key / FreshRSS 凭据 / token）；绝无其他
用户的数据（每用户库隔离 + 每请求服务端身份）。
"""

import json
import time
import zipfile
from io import BytesIO
from typing import Any

from lumirss.annotation_store import AnnotationStore, anchor_hash
from lumirss.entryref import InvalidEntryReference, decode_entry_ref
from lumirss.gpt_digest_configs import GptDigestConfigStore
from lumirss.gpt_digest_issues import GptDigestIssuesStore
from lumirss.library import LibraryStore
from lumirss.tags import TagStore
from lumirss.util import utc_now
from lumirss.workspaces import WorkspaceStore

WIZARD_SCHEMA = "lumirss-lumi-data-wizard/v1"
WIZARD_KIND = "lumirss-lumi-data"

_MAX_EXPORT_REFS = 500  # readingState 有界采集上限（截断如实标注）
_MAX_EXPORT_ANNOTATIONS = 500
_MAX_IMPORT_ATTEMPTS = 300  # apply 阶段每组件有界写入尝试

# 组件键 → 展示名（scope/预览界面共用同一份，避免两处漂移）。
COMPONENT_LABELS: dict[str, str] = {
    "sources": "订阅来源（地址/标题/分类，无凭据）",
    "readingState": "已读与收藏状态（按条目引用）",
    "annotations": "批注笔记",
    "tags": "标签与条目绑定",
    "workspaces": "工作区（含成员引用）",
    "bookmarks": "书签与笔记",
    "digest": "日报配置与期刊",
}

# 导入会话（内存、有界、短时效）——preview 与 apply 之间的交接物。
_IMPORT_SESSION_CAP = 4
_IMPORT_SESSION_TTL_S = 30 * 60


class WizardExportError(Exception):
    """导出侧失败——路由映射 502。"""


class WizardImportError(Exception):
    """导入包不合法（坏 zip / 坏 manifest / 未知组件）——路由映射 400。"""


class WizardImportSessionNotFound(Exception):
    """apply 引用了不存在/已过期的 preview 会话——路由映射 404。"""


def new_import_session_store() -> dict[str, dict[str, Any]]:
    return {}


def _prune_import_sessions(store: dict[str, dict[str, Any]]) -> None:
    now = time.monotonic()
    expired = [
        key
        for key, session in store.items()
        if now - float(session.get("created_mono", 0)) > _IMPORT_SESSION_TTL_S
    ]
    for key in expired:
        store.pop(key, None)
    while len(store) >= _IMPORT_SESSION_CAP:
        oldest = min(store, key=lambda k: store[k].get("created_mono", 0))
        store.pop(oldest, None)


def _component_count(key: str, payload: dict[str, Any]) -> int:
    if key == "digest":
        return len(payload.get("configs") or [])
    return len(payload.get("items") or [])


# ---------------------------------------------------------------------------
# 导出采集（只读）
# ---------------------------------------------------------------------------


async def collect_export_components(
    db: Any,
    *,
    control_adapter: Any = None,
    read_adapter: Any = None,
) -> dict[str, dict[str, Any]]:
    """逐组件采集（只读）。sources/readingState 需要适配器；适配器不可用
    （如未绑定）→ 这两个组件如实以 available:false 记录，绝不虚构。"""
    workspace_store = WorkspaceStore(db)
    library_store = LibraryStore(db)
    tag_store = TagStore(db)
    annotation_store = AnnotationStore(db)
    config_store = GptDigestConfigStore(db)
    issue_store = GptDigestIssuesStore(db)

    components: dict[str, dict[str, Any]] = {}

    # -- sources（订阅投影；无凭据） ------------------------------------
    if control_adapter is not None:
        try:
            subscriptions = await control_adapter.list_subscriptions()
            components["sources"] = {
                "available": True,
                "items": [
                    {
                        "feedUrl": s.feed_url,
                        "title": s.title,
                        "category": (s.category.label if s.category else None),
                    }
                    for s in subscriptions
                ],
            }
        except Exception as exc:  # noqa: BLE001 — 上游不可用如实报告
            components["sources"] = {
                "available": False,
                "reason": f"订阅清单不可用：{exc}",
                "items": [],
            }
    else:
        components["sources"] = {
            "available": False,
            "reason": "RSS 源绑定不可用",
            "items": [],
        }

    # -- readingState（已读/收藏，按条目引用；有界采集） ----------------
    if read_adapter is not None:
        try:
            # list_entries 无 limit 参数（上游分页口径）；这里在采集侧
            # 截断到 _MAX_EXPORT_REFS，截断与否如实标注。
            page = await read_adapter.list_entries(view="all")
            items = list(page.items)[:_MAX_EXPORT_REFS]
            components["readingState"] = {
                "available": True,
                "items": [
                    {
                        "ref": item.entryRef,
                        "read": bool(item.read),
                        "starred": bool(item.starred),
                    }
                    for item in items
                ],
                "truncated": bool(
                    page.upstreamContinuation is not None
                    or len(page.items) > _MAX_EXPORT_REFS
                ),
            }
        except Exception as exc:  # noqa: BLE001
            components["readingState"] = {
                "available": False,
                "reason": f"读取条目状态失败：{exc}",
                "items": [],
                "truncated": False,
            }
    else:
        components["readingState"] = {
            "available": False,
            "reason": "RSS 源绑定不可用",
            "items": [],
            "truncated": False,
        }

    # -- annotations ----------------------------------------------------
    annotations, annotations_complete = await annotation_store.list_all_bounded(
        _MAX_EXPORT_ANNOTATIONS
    )
    components["annotations"] = {
        "available": True,
        "items": annotations,
        "truncated": not annotations_complete,
    }

    # -- tags（标签 + 绑定，沿用 F39 口径） ------------------------------
    tags = await tag_store.list_tags()
    bindings: list[dict[str, Any]] = []
    for tag in tags[:_MAX_EXPORT_REFS]:
        refs = await tag_store.item_refs_for_tag(tag.id, limit=_MAX_EXPORT_REFS)
        bindings.append({"tag": tag.name, "itemRefs": refs})
    components["tags"] = {
        "available": True,
        "items": [{"name": tag.name} for tag in tags],
        "bindings": bindings,
    }

    # -- workspaces -------------------------------------------------------
    workspaces: list[dict[str, Any]] = []
    for summary in await workspace_store.list_workspaces():
        members = await workspace_store.list_items(summary.id, limit=500)
        workspaces.append(
            {
                "id": summary.id,
                "name": summary.name,
                "description": summary.description,
                "reserved": summary.reserved,
                "itemRefs": [member.item_ref for member in members],
            }
        )
    components["workspaces"] = {"available": True, "items": workspaces}

    # -- bookmarks --------------------------------------------------------
    components["bookmarks"] = {
        "available": True,
        "items": [
            {
                "itemType": b.item_type,
                "url": b.url,
                "rssItemRef": b.rss_item_ref,
                "title": b.title,
                "note": b.note,
                "createdAt": b.created_at,
            }
            for b in await library_store.list_all_bookmarks()
        ],
    }

    # -- digest（配置 + 期刊） -------------------------------------------
    digest_configs: list[dict[str, Any]] = []
    digest_issues: list[dict[str, Any]] = []
    for config in await config_store.list_configs():
        digest_configs.append(
            {
                "id": config["id"],
                "name": config["name"],
                "hour": config["hour"],
                "timezone": config["timezone"],
                "windowHours": config["windowHours"],
                "limitCount": config["limitCount"],
                "perSourceCap": config["perSourceCap"],
                "feedUrlAllow": config["feedUrlAllow"],
                "sourceKind": config["sourceKind"],
                "slots": config["slots"],
            }
        )
        for row in await issue_store.recent_issues(config["id"], 30):
            try:
                sections = json.loads(str(row["sections_json"] or "[]"))
            except ValueError:
                sections = []
            try:
                refs = json.loads(str(row["refs_json"] or "{}"))
            except ValueError:
                refs = {}
            digest_issues.append(
                {
                    "configId": config["id"],
                    "issueKey": str(row["issue_key"]),
                    "title": str(row["title"]),
                    "sections": sections,
                    "refs": refs,
                    "publishedAt": str(row["published_at"]),
                }
            )
    components["digest"] = {
        "available": True,
        "configs": digest_configs,
        "issues": digest_issues,
    }
    return components


def component_scope(components: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """scope 展示：每个组件的条数（available=false 如实标注 0 + 原因）。"""
    result: list[dict[str, Any]] = []
    for key, label in COMPONENT_LABELS.items():
        payload = components.get(key) or {"available": False, "reason": "缺失"}
        result.append(
            {
                "key": key,
                "label": label,
                "count": _component_count(key, payload)
                if payload.get("available")
                else 0,
                "available": bool(payload.get("available")),
                "reason": payload.get("reason"),
                "truncated": bool(payload.get("truncated")),
            }
        )
    return result


def build_export_zip(components: dict[str, dict[str, Any]]) -> bytes:
    """组件 → zip 字节（manifest.json + <key>.json；全部 JSON 为 UTF-8）。"""
    manifest = {
        "schema": WIZARD_SCHEMA,
        "kind": WIZARD_KIND,
        "exportedAt": utc_now(),
        "components": {
            key: _component_count(key, components.get(key) or {})
            for key in COMPONENT_LABELS
        },
    }
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
        )
        for key, payload in components.items():
            if key not in COMPONENT_LABELS:
                continue
            archive.writestr(
                f"{key}.json", json.dumps(payload, ensure_ascii=False, indent=1)
            )
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# 导入（preview → apply）
# ---------------------------------------------------------------------------


def parse_import_zip(data: bytes) -> dict[str, dict[str, Any]]:
    """zip 字节 → {component: payload}（校验 manifest schema/kind）。"""
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except (zipfile.BadZipFile, EOFError):
        raise WizardImportError("不是有效的 zip 归档。") from None
    with archive:
        try:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        except (KeyError, ValueError):
            raise WizardImportError("归档缺少有效的 manifest.json。") from None
        if not isinstance(manifest, dict):
            raise WizardImportError("manifest.json 形状不正确。")
        if str(manifest.get("schema") or "") != WIZARD_SCHEMA:
            raise WizardImportError(f"导出包 schema 不支持（期望 {WIZARD_SCHEMA}）。")
        if str(manifest.get("kind") or "") != WIZARD_KIND:
            raise WizardImportError("这不是 LumiRSS 个人数据导出包。")
        components: dict[str, dict[str, Any]] = {}
        for name in archive.namelist():
            if not name.endswith(".json") or name == "manifest.json":
                continue
            key = name[: -len(".json")]
            if key not in COMPONENT_LABELS:
                continue  # 未知组件忽略（向前兼容；不冒充认识）
            try:
                payload = json.loads(archive.read(name).decode("utf-8"))
            except ValueError:
                raise WizardImportError(f"组件文件 {name} 不是有效 JSON。") from None
            if not isinstance(payload, dict):
                raise WizardImportError(f"组件文件 {name} 形状不正确。")
            components[key] = payload
    if not components:
        raise WizardImportError("导出包里没有可识别的组件。")
    return components


async def preview_import(
    db: Any,
    components: dict[str, dict[str, Any]],
    *,
    control_adapter: Any = None,
    store: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """各组件计数 + 冲突（=已存在、将被跳过的项）。

    - sources 冲突：当前账号已订阅同一 feedUrl；
    - annotations 冲突：同 anchorHash 已存在；
    - tags 冲突：同名标签已存在（绑定仍会在 apply 时逐条幂等补挂）；
    - bookmarks 冲突：同 URL / 同 rss 引用的书签已存在；
    - readingState：不预判冲突（apply 时只对已存在引用生效，其余跳过）。
    """
    import secrets as _secrets

    tag_store = TagStore(db)
    annotation_store = AnnotationStore(db)
    library_store = LibraryStore(db)
    existing_bookmark_urls: set[str] = set()
    existing_bookmark_refs: set[str] = set()
    for bookmark in await library_store.list_all_bookmarks():
        if bookmark.url:
            existing_bookmark_urls.add(bookmark.url)
        if bookmark.rss_item_ref:
            existing_bookmark_refs.add(bookmark.rss_item_ref)

    existing_feeds: set[str] = set()
    if control_adapter is not None and "sources" in components:
        try:
            existing_feeds = {
                s.feed_url for s in await control_adapter.list_subscriptions()
            }
        except Exception:  # noqa: BLE001 — 预览拿不到订阅清单时冲突列空
            existing_feeds = set()

    existing_tag_names = {tag.name.lower() for tag in await tag_store.list_tags()}

    scope: list[dict[str, Any]] = []
    for key, payload in components.items():
        if key not in COMPONENT_LABELS:
            continue
        conflicts = 0
        if key == "sources":
            conflicts = sum(
                1
                for item in payload.get("items") or []
                if str(item.get("feedUrl") or "") in existing_feeds
            )
        elif key == "annotations":
            for item in (payload.get("items") or [])[:_MAX_IMPORT_ATTEMPTS]:
                try:
                    row_hash = anchor_hash(
                        str(item.get("entryRef") or ""), item.get("anchor") or {}
                    )
                    if await annotation_store.get_by_anchor_hash(row_hash) is not None:
                        conflicts += 1
                except Exception:  # noqa: BLE001 — 单条坏数据按冲突处理
                    conflicts += 1
        elif key == "bookmarks":
            conflicts = sum(
                1
                for item in payload.get("items") or []
                if (
                    (item.get("rssItemRef") and str(item.get("rssItemRef")) in existing_bookmark_refs)
                    or (not item.get("rssItemRef") and str(item.get("url") or "") in existing_bookmark_urls)
                )
            )
        elif key == "tags":
            names = {
                str(item.get("name") or "").strip().lower()
                for item in payload.get("items") or []
            }
            conflicts = len(names & existing_tag_names)
        scope.append(
            {
                "key": key,
                "label": COMPONENT_LABELS[key],
                "count": _component_count(key, payload),
                "conflicts": conflicts,
            }
        )

    import_id = "imp-" + _secrets.token_urlsafe(12)
    if store is not None:
        _prune_import_sessions(store)
        store[import_id] = {
            "created_mono": time.monotonic(),
            "components": components,
        }
    return {"importId": import_id, "components": scope}


async def apply_import(
    db: Any,
    session: dict[str, Any],
    selected: list[str],
    *,
    control_adapter: Any = None,
    read_adapter: Any = None,
) -> dict[str, Any]:
    """按所选组件合并（跳过已存在、只加新的）；返回逐组件结果。"""
    components = session.get("components") or {}
    unknown = [key for key in selected if key not in COMPONENT_LABELS]
    if unknown:
        raise WizardImportError(f"未知组件：{', '.join(unknown)}")

    async def _apply_sources() -> dict[str, Any]:
        payload = components.get("sources") or {}
        items = (payload.get("items") or [])[:_MAX_IMPORT_ATTEMPTS]
        if control_adapter is None:
            return {
                "added": 0,
                "skipped": 0,
                "failed": len(items),
                "reason": "RSS 源绑定不可用",
            }
        try:
            existing = {s.feed_url for s in await control_adapter.list_subscriptions()}
        except Exception:  # noqa: BLE001 — 拿不到现状时逐条让上游判冲突
            existing = set()
        added = skipped = failed = 0
        for item in items:
            feed_url = str(item.get("feedUrl") or "").strip()
            if not feed_url:
                failed += 1
                continue
            if feed_url in existing:
                skipped += 1
                continue
            title = str(item.get("title") or "").strip() or None
            try:
                await control_adapter.subscribe(feed_url, title=title)
                added += 1
                existing.add(feed_url)
            except Exception:  # noqa: BLE001 — 单源失败不拖垮整批
                failed += 1
        # 说明：分类（category）不在导入范围——跨实例的分类 id 不可移植，
        # 新订阅落入目标账号的默认分类（诚实省略，不冒充还原）。
        return {"added": added, "skipped": skipped, "failed": failed}

    async def _apply_reading_state() -> dict[str, Any]:
        payload = components.get("readingState") or {}
        items = (payload.get("items") or [])[:_MAX_IMPORT_ATTEMPTS]
        if read_adapter is None:
            return {
                "applied": 0,
                "skipped": len(items),
                "failed": 0,
                "reason": "RSS 源绑定不可用",
            }
        applied = skipped = 0
        for item in items:
            raw_ref = str(item.get("ref") or "").removeprefix("rss:")
            try:
                item_id = decode_entry_ref(raw_ref)
            except InvalidEntryReference:
                skipped += 1
                continue
            try:
                # 只对「已存在的引用」生效：先确认上游有这条，再设状态。
                await read_adapter.get_entry(item_id)
                await read_adapter.set_entry_state(
                    item_id,
                    read=bool(item.get("read")),
                    starred=bool(item.get("starred")),
                )
                applied += 1
            except Exception:  # noqa: BLE001 — 引用不存在/上游失败 → 诚实跳过
                skipped += 1
        return {"applied": applied, "skipped": skipped, "failed": 0}

    async def _apply_annotations() -> dict[str, Any]:
        payload = components.get("annotations") or {}
        items = (payload.get("items") or [])[:_MAX_IMPORT_ATTEMPTS]
        store = AnnotationStore(db)
        added = skipped = failed = 0
        for item in items:
            try:
                row_hash = anchor_hash(
                    str(item.get("entryRef") or ""), item.get("anchor") or {}
                )
                if await store.get_by_anchor_hash(row_hash) is not None:
                    skipped += 1
                    continue
                await store.create(
                    entry_ref=str(item.get("entryRef") or ""),
                    anchor=dict(item.get("anchor") or {}),
                    excerpt=item.get("excerpt"),
                    note=item.get("note"),
                    color=str(item.get("color") or "yellow"),
                )
                added += 1
            except Exception:  # noqa: BLE001 — 单条失败继续
                failed += 1
        return {"added": added, "skipped": skipped, "failed": failed}

    async def _apply_tags() -> dict[str, Any]:
        from lumirss.tags import TagInvalid

        payload = components.get("tags") or {}
        store = TagStore(db)
        added = skipped = failed = 0
        for binding in payload.get("bindings") or []:
            name = str(binding.get("tag") or "").strip()
            if not name:
                continue
            for ref in (binding.get("itemRefs") or [])[:_MAX_IMPORT_ATTEMPTS]:
                try:
                    await store.attach(str(ref), name)
                    added += 1  # attach 幂等：重复绑定原样返回，不产生重复行
                except TagInvalid:
                    skipped += 1
                except Exception:  # noqa: BLE001 — 单条失败继续
                    failed += 1
        return {"added": added, "skipped": skipped, "failed": failed}

    async def _apply_workspaces() -> dict[str, Any]:
        payload = components.get("workspaces") or {}
        store = WorkspaceStore(db)
        added = skipped = failed = 0
        existing_names = {w.name for w in await store.list_workspaces()}
        for item in (payload.get("items") or [])[:_MAX_IMPORT_ATTEMPTS]:
            name = str(item.get("name") or "").strip()
            if not name or item.get("reserved") or name in existing_names:
                skipped += 1
                continue
            try:
                created = await store.create_workspace(
                    name=name, description=str(item.get("description") or "")
                )
                existing_names.add(name)
                for ref in (item.get("itemRefs") or [])[:500]:
                    try:
                        await store.add_item(created.id, str(ref))
                    except Exception:  # noqa: BLE001 — 单成员失败不拖垮
                        continue
                added += 1
            except Exception:  # noqa: BLE001
                failed += 1
        return {"added": added, "skipped": skipped, "failed": failed}

    async def _apply_bookmarks() -> dict[str, Any]:
        payload = components.get("bookmarks") or {}
        store = LibraryStore(db)
        added = skipped = failed = 0
        for item in (payload.get("items") or [])[:_MAX_IMPORT_ATTEMPTS]:
            title = str(item.get("title") or "")
            note = str(item.get("note") or "")
            rss_ref = item.get("rssItemRef")
            url = str(item.get("url") or "") if rss_ref is None else ""
            try:
                if rss_ref:
                    _, created_flag = await store.create_rss_bookmark(
                        str(rss_ref), title or "(无标题)", note
                    )
                elif url:
                    _, created_flag = await store.create_url_bookmark(
                        url, title or "(无标题)", note
                    )
                else:
                    skipped += 1
                    continue
                if created_flag:
                    added += 1
                else:
                    skipped += 1
            except Exception:  # noqa: BLE001 — 单条失败继续
                failed += 1
        return {"added": added, "skipped": skipped, "failed": failed}

    async def _apply_digest() -> dict[str, Any]:
        payload = components.get("digest") or {}
        configs = GptDigestConfigStore(db)
        existing_names = {c["name"] for c in await configs.list_configs()}
        added = skipped = 0
        for item in (payload.get("configs") or [])[:50]:
            name = str(item.get("name") or "")
            if not name or name in existing_names:
                skipped += 1
                continue
            await configs.create_config(
                {
                    "name": name,
                    "hour": item.get("hour"),
                    "timezone": item.get("timezone"),
                    "windowHours": item.get("windowHours"),
                    "limitCount": item.get("limitCount"),
                    "perSourceCap": item.get("perSourceCap"),
                    "feedUrlAllow": item.get("feedUrlAllow"),
                    "sourceKind": item.get("sourceKind"),
                    "slots": item.get("slots"),
                }
            )
            existing_names.add(name)
            added += 1
        # 期刊只随「新建的配置」没有稳定映射（configId 跨实例不可移植），
        # 诚实省略——不冒充还原期刊。
        return {"added": added, "skipped": skipped, "failed": 0}

    runners = {
        "sources": _apply_sources,
        "readingState": _apply_reading_state,
        "annotations": _apply_annotations,
        "tags": _apply_tags,
        "workspaces": _apply_workspaces,
        "bookmarks": _apply_bookmarks,
        "digest": _apply_digest,
    }
    results: dict[str, Any] = {}
    for key in selected:
        runner = runners.get(key)
        if runner is not None:
            results[key] = await runner()
    return {"components": results}
