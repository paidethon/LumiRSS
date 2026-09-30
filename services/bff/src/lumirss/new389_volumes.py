"""NEW-389 分卷导出 —— 按用户指定容量把大型授权资料集分卷，每卷带
清单；导入时检查缺卷，绝不默默少导。

口径：

- 导出：用户选择书目（ids 或全部）与单卷字节上限（8KiB–1MiB）；
  记录按序塞卷，卷满即切；每卷 = {setId, index, of, items[], manifest}
  其中 manifest 携带本卷条目 id、字节量与卷内 sha256；set-manifest
  （卷数、全部条目 id、整体 sha256）随每卷一起返回，导入端只凭任意
  卷也能知道全集应有几卷；
- 校验（check）：收一组卷清单 → 逐卷状态 + 缺卷清单 + 缺失条目，
  只报告、不写入；
- 导入（import）：卷集不完整 → 409 + 缺卷/缺条目报告（不默默少导）；
  完整 → 逐条写入（external_id 已存在 = matched；新增 = added；
  写入异常 = failed 并带原因），并生成 NEW-390 对账单（expected =
  集清单全部条目，results = 逐条结果）——对账确认走 390 的端点。

per-user：导出与导入都在 member 自己的库。
"""

import hashlib
import json
import uuid as _uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.new381_bib import BibStore, _clean
from lumirss.storage import Database
from lumirss.util import utc_now

MIN_VOLUME_BYTES = 8 * 1024
MAX_VOLUME_BYTES = 1024 * 1024
MAX_RECORDS = 2000


class VolumeInvalid(ValueError):
    """分卷请求非法（映射 400）。"""


class VolumeSetIncomplete(Exception):
    """卷集不完整（映射 409）。携带缺卷报告。"""

    def __init__(self, report: dict[str, Any]) -> None:
        super().__init__("volume set incomplete")
        self.report = report


def _item_bytes(item: dict[str, Any]) -> int:
    return len(json.dumps(item, ensure_ascii=False).encode("utf-8"))


def split_volumes(
    records: list[dict[str, Any]], max_volume_bytes: int
) -> dict[str, Any]:
    if not records:
        raise VolumeInvalid("没有可分卷的资料。")
    if len(records) > MAX_RECORDS:
        raise VolumeInvalid(f"一次最多分卷 {MAX_RECORDS} 条资料。")
    if not MIN_VOLUME_BYTES <= max_volume_bytes <= MAX_VOLUME_BYTES:
        raise VolumeInvalid(
            f"单卷上限需在 {MIN_VOLUME_BYTES // 1024}KiB–{MAX_VOLUME_BYTES // 1024}KiB 之间。"
        )
    set_id = f"volset-{_uuid.uuid4().hex[:12]}"
    volumes: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_bytes = 0

    def _flush() -> None:
        nonlocal current, current_bytes
        if not current:
            return
        ids = [item["id"] for item in current]
        volume_blob = json.dumps(current, ensure_ascii=False, sort_keys=True)
        volumes.append(
            {
                "setId": set_id,
                "index": len(volumes) + 1,
                "of": 0,
                "items": current,
                "manifest": {
                    "itemIds": ids,
                    "bytes": current_bytes,
                    "sha256": hashlib.sha256(volume_blob.encode("utf-8")).hexdigest(),
                },
            }
        )
        current = []
        current_bytes = 0

    for record in records:
        size = _item_bytes(record)
        if current and current_bytes + size > max_volume_bytes:
            _flush()
        current.append(record)
        current_bytes += size
    _flush()
    for volume in volumes:
        volume["of"] = len(volumes)

    all_ids = [record["id"] for record in records]
    set_manifest = {
        "setId": set_id,
        "volumeCount": len(volumes),
        "itemCount": len(all_ids),
        "itemIds": all_ids,
        "maxVolumeBytes": max_volume_bytes,
        "sha256": hashlib.sha256(
            json.dumps(sorted(all_ids), ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
    }
    return {"setManifest": set_manifest, "volumes": volumes}


async def persist_set(db: Database, split: dict[str, Any]) -> str:
    await db.migrate()
    set_manifest = split["setManifest"]
    await db.execute(
        "INSERT INTO new389_volume_sets"
        " (id, volume_count, max_volume_bytes, total_bytes, volumes_json,"
        " item_count, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            set_manifest["setId"],
            set_manifest["volumeCount"],
            int(set_manifest["maxVolumeBytes"]),
            sum(int(v["manifest"]["bytes"]) for v in split["volumes"]),
            json.dumps(
                [
                    {"index": v["index"], "of": v["of"], **v["manifest"]}
                    for v in split["volumes"]
                ],
                ensure_ascii=False,
            ),
            set_manifest["itemCount"],
            utc_now(),
        ),
    )
    return str(set_manifest["setId"])


async def list_sets(db: Database) -> list[dict[str, Any]]:
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT id, volume_count, max_volume_bytes, total_bytes, volumes_json,"
        " item_count, created_at FROM new389_volume_sets"
        " ORDER BY created_at DESC, id ASC LIMIT 100"
    )
    return [
        {
            "setId": str(row["id"]),
            "volumeCount": int(row["volume_count"]),
            "maxVolumeBytes": int(row["max_volume_bytes"]),
            "totalBytes": int(row["total_bytes"]),
            "volumes": json.loads(str(row["volumes_json"])),
            "itemCount": int(row["item_count"]),
            "createdAt": str(row["created_at"]),
        }
        for row in rows
    ]


def _check_set(set_manifest: dict[str, Any], volumes: list[dict[str, Any]]) -> dict[str, Any]:
    expected_ids = [str(i) for i in set_manifest.get("itemIds") or []]
    expected_count = int(set_manifest.get("volumeCount") or 0)
    received: list[dict[str, Any]] = []
    problems: list[str] = []
    seen_ids: list[str] = []
    for volume in volumes:
        manifest = volume.get("manifest") or {}
        items = volume.get("items") or []
        if str(volume.get("setId") or "") != str(set_manifest.get("setId")):
            problems.append(f"卷 {volume.get('index')} 的 setId 与集清单不一致。")
            continue
        received.append(
            {
                "index": int(volume.get("index") or 0),
                "itemCount": len(items),
                "sha256": str(manifest.get("sha256") or ""),
            }
        )
        for item in items:
            item_id = str(item.get("id") or "")
            if item_id:
                seen_ids.append(item_id)
    unique_received = {entry["index"] for entry in received}
    missing_indexes = sorted(
        index for index in range(1, expected_count + 1) if index not in unique_received
    )
    missing_items = [item_id for item_id in expected_ids if item_id not in set(seen_ids)]
    complete = not missing_indexes and not missing_items and not problems
    return {
        "setId": set_manifest.get("setId"),
        "complete": complete,
        "expectedVolumes": expected_count,
        "receivedVolumes": len(received),
        "missingVolumes": missing_indexes,
        "missingItems": missing_items,
        "problems": problems,
        "received": received,
    }


async def check_volumes(
    db: Database, set_manifest: dict[str, Any], volumes: list[dict[str, Any]]
) -> dict[str, Any]:
    """收卷清单 → 完整性报告（零写入）。"""
    await db.migrate()
    if not isinstance(set_manifest, dict) or not set_manifest.get("setId"):
        raise VolumeInvalid("缺少卷集清单（setManifest）。")
    if not isinstance(volumes, list):
        raise VolumeInvalid("volumes 必须是数组。")
    report = _check_set(set_manifest, volumes)
    return report


async def export_volumes(
    db: Database, item_ids: list[str], max_volume_bytes: int
) -> dict[str, Any]:
    """导出分卷 + 台账。"""
    await db.migrate()
    ids = [str(ref).strip() for ref in item_ids if str(ref).strip()]
    records = (
        await BibStore(db).list_records()
        if not ids
        else await BibStore(db).get_records_by_ids(ids)
    )
    split = split_volumes(records, int(max_volume_bytes))
    await persist_set(db, split)
    split["setManifest"]["persistedAt"] = utc_now()
    return split


async def import_volumes(
    db: Database, set_manifest: dict[str, Any], volumes: list[dict[str, Any]]
) -> dict[str, Any]:
    """完整卷集 → 写入；缺卷 → 409 报告。返回 390 对账所需逐条结果。"""
    await db.migrate()
    report = _check_set(set_manifest, volumes)
    import_id = f"volimp-{_uuid.uuid4().hex[:12]}"
    if not report["complete"]:
        await db.execute(
            "INSERT INTO new389_volume_imports"
            " (id, set_id, status, received_volumes, expected_volumes, missing_json,"
            " added, matched, failed, reconciliation_id, created_at)"
            " VALUES (?, ?, 'incomplete', ?, ?, ?, 0, 0, 0, NULL, ?)",
            (
                import_id,
                str(set_manifest.get("setId") or ""),
                report["receivedVolumes"],
                report["expectedVolumes"],
                json.dumps(
                    {
                        "missingVolumes": report["missingVolumes"],
                        "missingItems": report["missingItems"][:200],
                        "problems": report["problems"],
                    },
                    ensure_ascii=False,
                ),
                utc_now(),
            ),
        )
        raise VolumeSetIncomplete({"importId": import_id, **report})

    keys = await BibStore(db).existing_keys("zotero_rdf")
    keys.update(await BibStore(db).existing_keys("ris"))
    results: list[dict[str, Any]] = []
    counters = {"added": 0, "matched": 0, "failed": 0}

    def _tx(conn: Any) -> None:
        conn.execute(
            "INSERT INTO new389_volume_imports"
            " (id, set_id, status, received_volumes, expected_volumes, missing_json,"
            " added, matched, failed, reconciliation_id, created_at)"
            " VALUES (?, ?, 'imported', ?, ?, '[]', ?, ?, ?, NULL, ?)",
            (
                import_id,
                str(set_manifest.get("setId") or ""),
                report["receivedVolumes"],
                report["expectedVolumes"],
                counters["added"],
                counters["matched"],
                counters["failed"],
                utc_now(),
            ),
        )
        for volume in volumes:
            for item in volume.get("items") or []:
                external_id = _clean(item.get("externalId"), 500)
                source_format = (
                    "ris" if str(item.get("format") or "") == "ris" else "zotero_rdf"
                )
                title = _clean(item.get("title"), 2000) or "(无题)"
                item_record_id = _clean(item.get("id"), 500)
                try:
                    if external_id and external_id in keys:
                        counters["matched"] += 1
                        results.append(
                            {
                                "externalId": external_id,
                                "recordId": item_record_id,
                                "title": title,
                                "status": "matched",
                                "detail": "该引用标识已存在，未重复写入。",
                            }
                        )
                        continue
                    if not external_id:
                        raise ValueError("缺少引用标识")
                    record_id = f"bib-{_uuid.uuid4().hex[:16]}"
                    conn.execute(
                        "INSERT INTO new381_bib_records"
                        " (id, source_format, external_id, title, creators_json,"
                        " pub_year, publication, publisher, url, doi, abstract,"
                        " item_type, tags_json, unsupported_fields_json,"
                        " import_batch_id, created_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?)",
                        (
                            record_id,
                            source_format,
                            external_id,
                            title,
                            json.dumps(item.get("creators") or [], ensure_ascii=False),
                            _clean(item.get("pubYear"), 10),
                            _clean(item.get("publication")),
                            _clean(item.get("publisher")),
                            _clean(item.get("url"), 2048),
                            _clean(item.get("doi"), 200),
                            _clean(item.get("abstract"), 8000),
                            _clean(item.get("itemType"), 100),
                            json.dumps(item.get("tags") or [], ensure_ascii=False),
                            import_id,
                            utc_now(),
                        ),
                    )
                    keys[external_id] = record_id
                    counters["added"] += 1
                    results.append(
                        {
                            "externalId": external_id,
                            "recordId": item_record_id,
                            "title": title,
                            "status": "added",
                            "detail": "",
                        }
                    )
                except (ValueError, TypeError, KeyError) as exc:
                    counters["failed"] += 1
                    results.append(
                        {
                            "externalId": external_id,
                            "recordId": item_record_id,
                            "title": title,
                            "status": "failed",
                            "detail": str(exc)[:200],
                        }
                    )
            conn.execute(
                "UPDATE new389_volume_imports SET added = ?, matched = ?, failed = ?"
                " WHERE id = ?",
                (counters["added"], counters["matched"], counters["failed"], import_id),
            )

    await transaction(db, _tx)
    expected_ids = [str(i) for i in set_manifest.get("itemIds") or []]
    # NEW-390 联动：完整导入自动生成逐项对账单（missing 由对账单按
    # externalId/recordId 双标识统一判定，避免重复/漏计）。
    from lumirss.new390_reconcile import create_reconciliation

    reconciliation = await create_reconciliation(
        db,
        expected_ids,
        results,
        source=f"volume:{set_manifest.get('setId')}",
    )
    await db.execute(
        "UPDATE new389_volume_imports SET reconciliation_id = ? WHERE id = ?",
        (reconciliation["id"], import_id),
    )
    return {
        "importId": import_id,
        "setId": set_manifest.get("setId"),
        "reconciliationId": reconciliation["id"],
        "reconciliation": reconciliation,
        "expectedItemIds": expected_ids,
        "results": reconciliation["results"],
        **counters,
    }


async def list_imports(db: Database) -> list[dict[str, Any]]:
    import json

    await db.migrate()
    rows = await db.fetch_all(
        "SELECT id, set_id, status, received_volumes, expected_volumes, missing_json,"
        " added, matched, failed, reconciliation_id, created_at"
        " FROM new389_volume_imports ORDER BY created_at DESC, id ASC LIMIT 100"
    )
    return [
        {
            "id": str(row["id"]),
            "setId": str(row["set_id"]),
            "status": str(row["status"]),
            "receivedVolumes": int(row["received_volumes"]),
            "expectedVolumes": int(row["expected_volumes"]),
            "missing": json.loads(str(row["missing_json"])),
            "added": int(row["added"]),
            "matched": int(row["matched"]),
            "failed": int(row["failed"]),
            "reconciliationId": (
                str(row["reconciliation_id"]) if row["reconciliation_id"] else None
            ),
            "createdAt": str(row["created_at"]),
        }
        for row in rows
    ]
