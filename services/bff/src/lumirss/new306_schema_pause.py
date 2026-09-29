"""NEW-306 API 抓取变更预警 —— 字段结构与保存样本不同且影响必要
字段时暂停该来源写入。

- 基线 = F043 的 confirmed_schema（用户确认过的结构快照）；
- diff_schema 报告 missing/type_changed：**必要字段**（基线 required
  且字段消失/类型改变/恒为 null）受影响 → 该来源进入写暂停：抓取
  仍被观察（诊断信息继续积累），但新条目**不再发布**，FreshRSS 端
  继续拿到 last-known-good（X-Lumi-Stale）—— 坏数据不静默流入；
- 只有用户确认新映射（resume：可选绑定新 field_map + 重新确认基线）
  才解除暂停；解除后上游仍坏 → 下一次拉取会再次暂停（诚实闭环）；
- per-user：暂停状态在 per-user 库的 api_sources 行上，A 的来源
  暂停对 B 不可见（B 访问 A 的来源/操作 404）。
"""

import json
from typing import Any

from lumirss.api_sources import diff_schema, observe_schema


def evaluate_required_drift(
    confirmed_schema: str | None, items: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """必要字段受影响的漂移 → 暂停载荷（含受影响字段清单）；否则 None。

    无基线（从未 confirm）不暂停 —— 预警只对用户确认过的契约生效。"""
    drift = diff_schema(confirmed_schema, observe_schema(items))
    if drift is None:
        return None
    baseline: dict[str, Any] = {}
    try:
        loaded = json.loads(confirmed_schema) if confirmed_schema else {}
        if isinstance(loaded, dict):
            baseline = loaded
    except json.JSONDecodeError:
        return None
    missing = sorted(drift.get("missing", []))
    # type_changed 只在「必要字段」上触发暂停；可选字段类型变化仍走
    # F043 的 advisory 报告（mark_drift），不阻断发布。
    required_fields = {
        field
        for field, spec in baseline.items()
        if isinstance(spec, dict) and bool(spec.get("required"))
    }
    type_changed = sorted(set(drift.get("type_changed", [])) & required_fields)
    if not missing and not type_changed:
        return None
    return {"missing": missing, "typeChanged": type_changed}


def pause_reason_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    if payload["missing"]:
        parts.append("缺失必要字段：" + "、".join(payload["missing"]))
    if payload["typeChanged"]:
        parts.append("必要字段类型变化：" + "、".join(payload["typeChanged"]))
    return "；".join(parts) + "。已暂停该来源写入，请确认新映射后恢复。"
