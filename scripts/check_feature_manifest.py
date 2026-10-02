#!/usr/bin/env python3
"""校验 docs/feature-manifest.json（R09 机读功能清单）的结构与一致性。

门禁点：
1. 顶层 schema 与必填字段、字段取值合法（status / permission / group）；
2. `id` 全局唯一；
3. 每条 `doc` slug 必须对应 `docs/<slug>.md` 真实存在（清单与文档站
   不失步）；
4. `screenshot`：null 合法；占位值（"pending" / 空串）**不允许**把任何
   条目标为 `published: true`；真实路径必须是 `docs/public/` 下存在
   的文件（截图阶段的产物直接被站点服务）；
5. `legacyId`（可空字符串）：非空时必须能在 docs/implementation-status.json
   的任务 id 里找到（桥接不失步）。

`published` 是可选布尔（缺省 false）：只有截图真实落盘后才允许置真，
作为"该功能在文档站带图发布"的显式标记。当前清单全部 screenshot=null，
本门禁照常通过——不阻塞截图工作。

用法: python3 scripts/check_feature_manifest.py [repo 根目录，默认脚本上级]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "docs" / "feature-manifest.json"
LEDGER = ROOT / "docs" / "implementation-status.json"
DOCS = ROOT / "docs"

SCHEMA = "lumi.feature-manifest/1"
REQUIRED_FIELDS = (
    "id",
    "group",
    "name",
    "entry",
    "permission",
    "prerequisites",
    "status",
    "doc",
    "screenshot",
    "verify",
)
ALLOWED_STATUS = {"available", "partial", "admin-only", "config-required"}
ALLOWED_PERMISSION = {"member", "admin", "owner"}
ALLOWED_GROUPS = {"reading", "sources", "organize", "ai", "admin"}
SCREENSHOT_PLACEHOLDERS = {"pending", ""}
ENTRY_EVIDENCE_HINT = ("apps/web", "services/bff", "settings", "/admin", "GET /api", "POST /api", "PUT /api", "PATCH /api", "DELETE /api", "侧栏", "设置", "来源中心", "阅读页", "工作区", "搜索页", "标签页", "列表")


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def main() -> int:
    errors: list[str] = []

    if not MANIFEST.is_file():
        print(f"FAIL: 找不到 {MANIFEST}")
        return 1
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"FAIL: manifest 不是合法 JSON：{exc}")
        return 1

    if data.get("schema") != SCHEMA:
        fail(errors, f"schema 必须是 {SCHEMA!r}，实际 {data.get('schema')!r}")
    if not isinstance(data.get("generated_at"), str) or not data["generated_at"]:
        fail(errors, "generated_at 必须是非空字符串")

    features = data.get("features")
    if not isinstance(features, list) or not features:
        fail(errors, "features 必须是非空数组")
        features = []

    # legacyId 桥接目标：台账任务 id 全集（台账缺失时不校验 legacyId）。
    ledger_ids: set[str] | None = None
    if LEDGER.is_file():
        try:
            ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
            ids = {t.get("id") for t in ledger.get("tasks", []) if isinstance(t, dict)}
            ledger_ids = {i for i in ids if isinstance(i, str)}
        except json.JSONDecodeError:
            ledger_ids = None  # 台账坏掉不是本门禁的职责

    seen: set[str] = set()
    for idx, feat in enumerate(features):
        if not isinstance(feat, dict):
            fail(errors, f"features[{idx}] 不是对象")
            continue
        fid = feat.get("id")
        label = f"features[{idx}]({fid})"
        for field in REQUIRED_FIELDS:
            if field not in feat:
                fail(errors, f"{label} 缺少必填字段 {field}")
        if not isinstance(fid, str) or not fid:
            fail(errors, f"{label} id 必须是非空字符串")
            continue
        if fid in seen:
            fail(errors, f"{label} id 重复")
        seen.add(fid)

        status = feat.get("status")
        if status not in ALLOWED_STATUS:
            fail(errors, f"{label} status 非法：{status!r}（允许 {sorted(ALLOWED_STATUS)}）")
        permission = feat.get("permission")
        if permission not in ALLOWED_PERMISSION:
            fail(errors, f"{label} permission 非法：{permission!r}")
        group = feat.get("group")
        if group not in ALLOWED_GROUPS:
            fail(errors, f"{label} group 非法：{group!r}")

        entry = feat.get("entry")
        if not isinstance(entry, str) or not any(h in entry for h in ENTRY_EVIDENCE_HINT):
            fail(errors, f"{label} entry 缺少入口证据（需要 UI 路径或 file:line / API 路由）")

        doc = feat.get("doc")
        if isinstance(doc, str) and doc:
            doc_file = DOCS / f"{doc}.md"
            if not doc_file.is_file():
                fail(errors, f"{label} doc slug 不存在：{doc} → docs/{doc}.md")
        else:
            fail(errors, f"{label} doc 必须是非空 slug")

        screenshot = feat.get("screenshot")
        published = feat.get("published", False)
        if screenshot is None:
            if published is True:
                fail(errors, f"{label} screenshot 为 null 却标了 published: true")
        elif not isinstance(screenshot, str) or screenshot in SCREENSHOT_PLACEHOLDERS:
            if published is True:
                fail(errors, f"{label} screenshot 是占位值却不允许标 published: true")
        else:
            # 真实路径：必须落在 docs/public/ 且文件存在（站点直接服务该目录）。
            shot = Path(screenshot)
            public = DOCS / "public"
            if not shot.is_absolute():
                shot = ROOT / shot
            try:
                shot.relative_to(public)
            except ValueError:
                fail(errors, f"{label} screenshot 必须位于 docs/public/ 下：{screenshot!r}")
            else:
                if not shot.is_file():
                    fail(errors, f"{label} screenshot 文件不存在：{screenshot}")
                if published is not True:
                    fail(errors, f"{label} screenshot 已落盘但仍未标 published: true（请回填后同步置真）")

        legacy = feat.get("legacyId", None)
        if legacy is not None:
            if not isinstance(legacy, str) or not legacy:
                fail(errors, f"{label} legacyId 必须是 null 或非空字符串")
            elif ledger_ids is not None and legacy not in ledger_ids:
                fail(errors, f"{label} legacyId {legacy!r} 不在 implementation-status.json 任务 id 中")

        prereq = feat.get("prerequisites")
        if not isinstance(prereq, list) or not all(isinstance(p, str) for p in prereq):
            fail(errors, f"{label} prerequisites 必须是字符串数组")

    if errors:
        print("FEATURE MANIFEST FAIL")
        for e in errors:
            print(" -", e)
        return 1

    from collections import Counter

    by_status = Counter(f.get("status") for f in features if isinstance(f, dict))
    pending = sum(1 for f in features if isinstance(f, dict) and f.get("screenshot") is None)
    print(
        f"feature manifest OK: {len(features)} 条，status {dict(by_status)}，"
        f"screenshot 待生成 {pending} 条"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
