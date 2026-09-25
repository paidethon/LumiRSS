"""N197 回滚就绪检查 — 只读聚合「能不能回滚」的要素清单。

BFF 没有 Docker 访问权（架构红线）：前一镜像是否存在不由 BFF 去
`docker image list`，而是读 ./lumirss `snapshot_for_rollback` 写下的
回滚快照清单（``LUMIRSS_ROLLBACK_MANIFEST_FILE``，与 N196 deploy-status
同一挂载思路——脚本侧写、BFF 只读透传口径）。

- previousImage: manifest 存在且带非空 previousImageTag → present；
  未配置/不存在/坏文件 → absent + 原因（诚实，绝不冒充可回滚）。
- backup: ``LUMIRSS_BACKUP_DIR`` 里最新的 ``*.backup`` 归档 + N186
  verify_backup_findings 的只读完整性校验结论（ok 才算 verifiable）。
- dbDowngrade: 诚实限制说明——SQLite 迁移只向前，回滚旧镜像后旧代码
  遇到新 schema 不做降级迁移；备份 schema 版本与当前不一致时
  canRollback 如实为 false。
- canRollback = previousImage present AND backup verifiable AND
  备份与当前 schema 版本一致。本端点永远只给清单——回滚动作只属于
  运维侧 ``./lumirss rollback``，这里没有任何执行控件。
"""

import json
from pathlib import Path
from typing import Any

ROLLBACK_MANIFEST_SCHEMA = "lumirss-rollback-manifest/v1"
_MAX_MANIFEST_BYTES = 64 * 1024


def read_rollback_manifest(path_value: str) -> dict[str, Any]:
    """端点口径的只读读取（永不抛出）；坏文件/未配置都如实报告。"""
    if not path_value.strip():
        return {
            "state": "absent",
            "reason": "LUMIRSS_ROLLBACK_MANIFEST_FILE is not configured — rollback snapshot tracking is not reported.",
            "previousImageTag": None,
        }
    path = Path(path_value.strip())
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {
            "state": "absent",
            "reason": "No rollback snapshot manifest found (no deploy/update has run with tracking configured).",
            "previousImageTag": None,
        }
    if len(raw) > _MAX_MANIFEST_BYTES:
        return {
            "state": "absent",
            "reason": "Rollback manifest file is implausibly large — refusing to read it.",
            "previousImageTag": None,
        }
    try:
        data = json.loads(raw)
    except ValueError:
        return {
            "state": "absent",
            "reason": "Rollback manifest file is not valid JSON.",
            "previousImageTag": None,
        }
    if not isinstance(data, dict) or str(data.get("schema", "")) != ROLLBACK_MANIFEST_SCHEMA:
        return {
            "state": "absent",
            "reason": f"Rollback manifest schema mismatch (expected {ROLLBACK_MANIFEST_SCHEMA}).",
            "previousImageTag": None,
        }
    tag = data.get("previousImageTag")
    if not isinstance(tag, str) or not tag.strip():
        return {
            "state": "absent",
            "reason": "Rollback manifest carries no previous image tag.",
            "previousImageTag": None,
        }
    return {"state": "present", "reason": None, "previousImageTag": tag.strip()}


def latest_backup_path(backup_dir_value: str) -> Path | None:
    """LUMIRSS_BACKUP_DIR 里最新的 ``*.backup`` 归档（名字排序 = 时间戳
    序，lumirss-YyyyMmddThhMMssZ.backup 命名保证）；目录不存在 → None。"""
    if not backup_dir_value.strip():
        return None
    directory = Path(backup_dir_value.strip())
    if not directory.is_dir():
        return None
    candidates = sorted(directory.glob("*.backup"))
    return candidates[-1] if candidates else None


def build_rollback_readiness(
    *,
    manifest: dict[str, Any],
    backup_report: dict[str, Any] | None,
    backup_name: str | None,
    current_schema_version: int | None,
    backup_schema_version: int | None,
    backup_dir_configured: bool,
) -> dict[str, Any]:
    """纯函数组装（可独立测试）：输入全部是只读采集到的真实状态。"""
    image_present = manifest.get("state") == "present"
    backup_ok = bool(backup_report and backup_report.get("ok") is True)
    schema_unchanged = (
        current_schema_version is not None
        and backup_schema_version is not None
        and int(backup_schema_version) == int(current_schema_version)
    )
    can_rollback = bool(image_present and backup_ok and schema_unchanged)
    return {
        "canRollback": can_rollback,
        "previousImage": {
            "state": "present" if image_present else "absent",
            "tag": manifest.get("previousImageTag"),
            "reason": None if image_present else manifest.get("reason"),
        },
        "backup": {
            "state": "verified" if backup_ok else ("absent" if backup_name is None else "unverified"),
            "name": backup_name,
            "reason": None if backup_ok else (
                None if backup_name is None else (
                    "校验未通过（见 findings）" if backup_report else (
                        "未配置 LUMIRSS_BACKUP_DIR" if not backup_dir_configured
                        else "备份目录中没有 *.backup 归档"
                    )
                )
            ),
            "verifyOk": backup_ok,
            "findings": (backup_report or {}).get("findings") if backup_report else None,
        },
        "schema": {
            "current": current_schema_version,
            "backup": backup_schema_version,
            "unchanged": schema_unchanged,
        },
        "dbDowngrade": (
            "SQLite 迁移只向前：回滚到旧镜像后，旧代码不会（也不能）把"
            "数据库降级回旧 schema。备份与当前 schema 版本一致时回滚才是"
            "就绪的；否则新 schema 已落库，旧镜像只能在新库上运行。"
        ),
        "note": "本检查只读。回滚由运维侧 ./lumirss rollback 执行——这里没有任何执行控件。",
    }
