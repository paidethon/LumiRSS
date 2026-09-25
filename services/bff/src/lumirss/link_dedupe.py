"""N047 快速筛除已收录链接 —— canonical URL 撞车提示（非阻断）。

加入必读队列 / 加入工作区时，把新条目的 URL 规范化（url_normalize，
保守规则：宁漏勿错合），与「其他待处理队列行 + 队列冻结快照成员 +
（工作区路径）同工作区既有成员」的规范化 URL 对比；命中 → 在**创建
成功**的响应里附 ``duplicateWarning``（非阻断——条目已加入，绝不因
撞车拒绝写入）。

- 只比 canonical URL：不同 URL 即使标题相似也绝不提示（没有标题
  相似度合并——诚实避免误报）；
- 比较范围有界：候选 ref 集合 ≤ 500，URL 解析不出 / 非 http(s) 的
  条目不参与（normalize 返回 None = 放行）。
"""

from typing import Any

from lumirss.storage import Database
from lumirss.url_normalize import normalize_content_url

_CANDIDATE_CAP = 500


async def _url_by_refs(db: Database, refs: list[str]) -> dict[str, str]:
    """裸 entryRef → url（投影缺失的 ref 不出现在结果里）。"""
    bare = [ref[4:] if ref.startswith("rss:") else ref for ref in refs]
    bare = [ref for ref in bare if ref]
    if not bare:
        return {}
    placeholders = ",".join("?" for _ in bare)
    rows = await db.fetch_all(
        f"SELECT entry_ref, url FROM search_entries WHERE entry_ref IN ({placeholders})",
        tuple(bare),
    )
    return {str(row["entry_ref"]): str(row["url"] or "") for row in rows}


async def _queue_candidate_refs(db: Database, exclude_ref: str) -> list[tuple[str, str]]:
    """候选：(itemRef, scope)。今日队列 pending 行 + 全部冻结快照成员。

    reading_queue.entry_ref 与快照 payload 的 item_ref 都已是统一
    ItemRef（``rss:<entryRef>``）——原样作为候选 ref；``exclude_ref``
    接受 ItemRef 或裸 entryRef（刚加入的行本身就在 pending 里，排除
    不做会导致「自己撞自己」）。"""
    bare_exclude = exclude_ref[4:] if exclude_ref.startswith("rss:") else exclude_ref
    candidates: list[tuple[str, str]] = []
    rows = await db.fetch_all(
        "SELECT entry_ref FROM reading_queue WHERE queue_date = ?"
        " AND status = 'pending' AND entry_ref NOT IN (?, ?)"
        " ORDER BY position ASC LIMIT ?",
        (_today(), bare_exclude, exclude_ref, _CANDIDATE_CAP),
    )
    for row in rows:
        candidates.append((str(row["entry_ref"]), "queue"))
    snapshot_rows = await db.fetch_all(
        "SELECT payload_json FROM queue_snapshots ORDER BY rowid DESC LIMIT 50"
    )
    import json as _json

    seen: set[str] = set()
    for row in snapshot_rows:
        try:
            payload = _json.loads(str(row["payload_json"]))
        except ValueError:
            continue
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            continue
        for entry in items:
            if not isinstance(entry, dict):
                continue
            ref = entry.get("item_ref")
            bare = ref[4:] if isinstance(ref, str) and ref.startswith("rss:") else ref
            if (
                not isinstance(ref, str)
                or bare == bare_exclude
                or ref in seen
            ):
                continue
            seen.add(ref)
            candidates.append((ref, "snapshot"))
            if len(candidates) >= _CANDIDATE_CAP * 2:
                break
        if len(candidates) >= _CANDIDATE_CAP * 2:
            break
    return candidates


def _today() -> str:
    from lumirss.reading_queue import today_queue_date

    return today_queue_date()


async def find_duplicate_for_ref(
    db: Database,
    item_ref: str,
    *,
    extra_refs: list[tuple[str, str]] | None = None,
) -> dict[str, Any] | None:
    """返回 {duplicateOf: {ref, scope, title?}} 或 None。

    ``extra_refs``：工作区路径补充的同工作区成员 [(itemRef, scope)]。
    """
    await db.migrate()
    url_map = await _url_by_refs(db, [item_ref])
    my_url = normalize_content_url(url_map.get(item_ref[4:] if item_ref.startswith("rss:") else item_ref, ""))
    if my_url is None:
        return None  # 解析不出 canonical URL：不提示（宁漏勿错）
    candidates = await _queue_candidate_refs(db, exclude_ref=item_ref)
    if extra_refs:
        known = {ref for ref, _ in candidates}
        for ref, scope in extra_refs:
            if ref != item_ref and ref not in known:
                candidates.append((ref, scope))
    if not candidates:
        return None
    cand_urls = await _url_by_refs(db, [ref for ref, _ in candidates])
    titles = await _title_by_refs(db, [ref for ref, _ in candidates])
    for ref, scope in candidates:
        bare = ref[4:] if ref.startswith("rss:") else ref
        other = normalize_content_url(cand_urls.get(bare, ""))
        if other is not None and other == my_url:
            hit: dict[str, Any] = {"ref": ref, "scope": scope}
            title = titles.get(bare)
            if title:
                hit["title"] = title
            return {"duplicateOf": hit}
    return None


async def _title_by_refs(db: Database, refs: list[str]) -> dict[str, str]:
    bare_refs = [ref[4:] if ref.startswith("rss:") else ref for ref in refs]
    bare_refs = [ref for ref in bare_refs if ref]
    if not bare_refs:
        return {}
    placeholders = ",".join("?" for _ in bare_refs)
    rows = await db.fetch_all(
        f"SELECT entry_ref, title FROM search_entries WHERE entry_ref IN ({placeholders})",
        tuple(bare_refs),
    )
    return {str(row["entry_ref"]): str(row["title"] or "") for row in rows}
