"""NEW-297 邮件导入规则预览 —— 写入前用样本检查主题清理、标签和来源
映射规则，确认后应用于本批。

诚实口径（硬规则）：

- 预览与真实导入走【同一条规则应用函数】（apply_rules）：预览零写入，
  确认后的导入按完全相同的变换落库——预览不是另一个实现；
- 规则只有三种、全部显式配置：subject_clean（正则去前缀）、tag
  （本批统一加标签）、source_map（本批按发件地址指定来源标签）；
- source_map 是【本批作用域】：与 NEW-294 的持久映射并存——持久映射
  先落底，本批规则可覆盖该批结果；两种来源都在响应里如实区分；
- 正则编译失败 → 422（不静默跳过规则，避免「以为清了其实没清」）。

per-user：规则表在 per-user 库，A 的规则对 B 不存在。
"""

import json
import re
import uuid
from typing import Any

from lumirss.new291_email_import import parse_eml
from lumirss.storage import Database
from lumirss.util import utc_now

KINDS = ("subject_clean", "tag", "source_map")
_MAX_RULES = 20

HONESTY_NOTE = (
    "预览与确认后的导入使用同一条规则应用路径；来源映射是本批作用域，"
    "与持久映射（NEW-294）分开标注，正则无效时整批拒绝而不是静默跳过。"
)


class RuleInvalid(ValueError):
    """规则负载非法（映射 422）。"""


def clean_rules(raw: Any) -> list[dict[str, Any]]:
    """校验规则清单：三种 kind 各自的 config 形状 + 正则可编译。"""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise RuleInvalid("rules 必须是数组。")
    if len(raw) > _MAX_RULES:
        raise RuleInvalid(f"规则最多 {_MAX_RULES} 条。")
    rules: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise RuleInvalid("rules 的元素必须是对象。")
        kind = item.get("kind")
        if kind not in KINDS:
            raise RuleInvalid(f"kind 必须是 {'、'.join(KINDS)} 之一。")
        config = item.get("config") or {}
        if not isinstance(config, dict):
            raise RuleInvalid("config 必须是对象。")
        if kind == "subject_clean":
            pattern = config.get("pattern")
            if not isinstance(pattern, str) or not pattern:
                raise RuleInvalid("subject_clean 需要 pattern（正则文本）。")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise RuleInvalid(f"正则无法编译：{exc}") from exc
            replacement = config.get("replacement", "")
            if not isinstance(replacement, str):
                raise RuleInvalid("replacement 必须是字符串（可为空）。")
            rules.append(
                {
                    "kind": kind,
                    "config": {"pattern": pattern, "replacement": replacement},
                }
            )
        elif kind == "tag":
            value = config.get("value")
            if not isinstance(value, str) or not value.strip():
                raise RuleInvalid("tag 需要 value（非空文本）。")
            rules.append({"kind": kind, "config": {"value": value.strip()[:60]}})
        else:  # source_map
            from_addr = config.get("fromAddr")
            label = config.get("sourceLabel")
            if not isinstance(from_addr, str) or "@" not in from_addr:
                raise RuleInvalid("source_map 需要 fromAddr（包含 @）。")
            if not isinstance(label, str) or not label.strip():
                raise RuleInvalid("source_map 需要 sourceLabel（非空文本）。")
            rules.append(
                {
                    "kind": kind,
                    "config": {
                        "fromAddr": from_addr.strip().lower(),
                        "sourceLabel": label.strip()[:120],
                    },
                }
            )
    return rules


def apply_rules(
    parsed: dict[str, Any], rules: list[dict[str, Any]], *,
    persisted_label: str = ""
) -> dict[str, Any]:
    """对一份解析结果应用规则（预览/导入共用的唯一实现）。

    返回 {subject, tags, sourceLabel, sourceOrigin}；sourceOrigin 如实
    区分 batch-rule / persisted（NEW-294）/ none。
    """
    subject = str(parsed.get("subject") or "")
    tags: list[str] = []
    source_label = persisted_label
    source_origin = "persisted" if persisted_label else "none"
    for rule in rules:
        kind = rule["kind"]
        config = rule["config"]
        if kind == "subject_clean":
            subject = re.sub(str(config["pattern"]), str(config["replacement"]), subject)
        elif kind == "tag":
            value = str(config["value"])
            if value not in tags:
                tags.append(value)
        else:  # source_map：本批规则覆盖（优先级高于持久映射）
            if str(parsed.get("from_addr") or "").lower() == str(config["fromAddr"]):
                source_label = str(config["sourceLabel"])
                source_origin = "batch-rule"
    return {
        "subject": subject[:500],
        "tags": tags,
        "sourceLabel": source_label,
        "sourceOrigin": source_origin,
    }


class ImportRuleStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def preview(self, raw_files: Any, raw_rules: Any) -> dict[str, Any]:
        """样本预览：解析 + 规则变换，零写入；坏文件如实标注。"""
        from lumirss.new291_email_import import _clean_files
        from lumirss.new294_email_source_maps import SourceMapStore

        files = _clean_files(raw_files)
        rules = clean_rules(raw_rules)
        await self._db.migrate()
        persisted = await SourceMapStore(self._db).addr_map()
        samples: list[dict[str, Any]] = []
        for index, file in enumerate(files):
            filename = str(file.get("filename") or f"邮件-{index + 1}.eml")
            content = file.get("content")
            if not isinstance(content, str) or not content:
                samples.append({"filename": filename, "status": "failed", "reason": "文件内容为空。"})
                continue
            try:
                parsed = parse_eml(content.encode("utf-8"))
            except Exception as exc:  # noqa: BLE001 — 预览也如实给失败原因
                samples.append({"filename": filename, "status": "failed", "reason": str(exc)})
                continue
            applied = apply_rules(
                parsed, rules, persisted_label=persisted.get(parsed["from_addr"].lower(), "")
            )
            samples.append(
                {
                    "filename": filename,
                    "status": "ok",
                    "subjectRaw": parsed["subject"],
                    "subject": applied["subject"],
                    "tags": applied["tags"],
                    "fromAddr": parsed["from_addr"],
                    "sourceLabel": applied["sourceLabel"],
                    "sourceOrigin": applied["sourceOrigin"],
                    "messageId": parsed["message_id"],
                }
            )
        return {
            "samples": samples,
            "rules": rules,
            "honestyNote": HONESTY_NOTE,
        }

    async def list_rules(self) -> dict[str, Any]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, kind, config_json, enabled, created_at"
            " FROM email_import_rules ORDER BY created_at ASC, id ASC"
        )
        return {
            "items": [
                {
                    "id": str(r["id"]),
                    "kind": str(r["kind"]),
                    "config": json.loads(str(r["config_json"] or "{}")),
                    "enabled": bool(r["enabled"]),
                    "createdAt": str(r["created_at"]),
                }
                for r in rows
            ]
        }

    async def save_rule(self, raw: Any) -> dict[str, Any]:
        (cleaned,) = clean_rules([raw])
        rule_id = f"eir-{uuid.uuid4().hex[:20]}"
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO email_import_rules (id, kind, config_json, enabled,"
            " created_at) VALUES (?, ?, ?, 1, ?)",
            (rule_id, cleaned["kind"], json.dumps(cleaned["config"], ensure_ascii=False), utc_now()),
        )
        return {"id": rule_id, "kind": cleaned["kind"], "config": cleaned["config"]}

    async def delete_rule(self, rule_id: str) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id FROM email_import_rules WHERE id = ?", (rule_id,)
        )
        if row is None:
            return False
        await self._db.execute(
            "DELETE FROM email_import_rules WHERE id = ?", (rule_id,)
        )
        return True
