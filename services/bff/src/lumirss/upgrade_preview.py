"""N195 升级影响预览 — 发布清单 × 当前版本 × 迁移差异的只读推演。

输入（全部只读）：
- release-manifest.json：路径来自 LUMIRSS_RELEASE_MANIFEST（发布流水线
  publish-images.yml 的产物，运营者放置/挂载）。未配置 / 文件缺失 /
  解析失败 / schema 不符 → ``available: false`` + 如实 reason（绝不
  编造「没有更新」或「安全可升」）。
- 当前版本：LumiSettings.LUMIRSS_VERSION（构建 provenance）。
- 迁移差异：manifest 携带的目标迁移清单（CI 从目标代码树枚举）对照
  控制库 schema_migrations 已应用集合 → newMigrations = 目标有而本地
  未应用的文件名（升序）。

阻断（blocked + blockedReason，诚实优先）：
- 目标版本 == 当前版本（无可升级内容）；
- 目标版本 < 当前版本（降级——回滚走 ./lumirss rollback，不是 update）;
- 本地已应用迁移不在目标清单内（数据库超前于目标——升级会把新代码
  旧库结构跑在旧镜像上，任何写入都可能踩新列）。

minCompat：manifest 的可选 min_compat 字段（CI 用最近一个发布 tag
填写）原样透传；manifest 没给就是 null，绝不推测。
"""

import json
import sqlite3
from pathlib import Path

MANIFEST_SCHEMA = "lumirss-release-manifest/v1"

_PREVIEW_FIELDS = (
    "available",
    "reason",
    "currentVersion",
    "targetVersion",
    "newMigrations",
    "minCompat",
    "blocked",
    "blockedReason",
)


def _unavailable(reason: str) -> dict[str, object]:
    return {
        "available": False,
        "reason": reason,
        "currentVersion": None,
        "targetVersion": None,
        "newMigrations": [],
        "minCompat": None,
        "blocked": False,
        "blockedReason": None,
    }


def _version_tuple(version: str) -> tuple[int, ...] | None:
    """容错语义化版本比较（x.y.z 的 1-3 段数字；其余形状 → None）。"""
    parts = version.strip().lstrip("v").split(".")
    if not 1 <= len(parts) <= 3:
        return None
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


def _compare_versions(left: str, right: str) -> int | None:
    """-1/0/1，无法比较时 None（调用方不得据此阻断）。"""
    a, b = _version_tuple(left), _version_tuple(right)
    if a is None or b is None:
        return None
    width = max(len(a), len(b))
    a += (0,) * (width - len(a))
    b += (0,) * (width - len(b))
    return (a > b) - (a < b)


def _migration_version(name: str) -> int | None:
    base = name.rsplit("/", 1)[-1]
    if len(base) >= 4 and base[:4].isdigit():
        return int(base[:4])
    return None


def _applied_migration_versions(control_db) -> set[int]:
    """控制库 schema_migrations 的已应用版本号（读失败 = 空集 + 上抛语义由调用方定）。"""
    connection = control_db._connect()  # noqa: SLF001 — 同模块族内部读取
    try:
        rows = connection.execute("SELECT version FROM schema_migrations").fetchall()
        return {int(row["version"]) for row in rows}
    except sqlite3.Error:
        return set()
    finally:
        connection.close()


def _read_manifest(path: Path) -> tuple[dict[str, object] | None, str | None]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None, "release manifest file not readable (missing or permissions)."
    try:
        data = json.loads(raw)
    except ValueError:
        return None, "release manifest is not valid JSON."
    if not isinstance(data, dict):
        return None, "release manifest is not a JSON object."
    if str(data.get("schema", "")) != MANIFEST_SCHEMA:
        return None, f"release manifest schema mismatch (expected {MANIFEST_SCHEMA})."
    if not str(data.get("version", "")).strip():
        return None, "release manifest does not declare a version."
    return data, None


def build_upgrade_preview(
    *,
    manifest_path: str,
    current_version: str,
    control_db,
) -> dict[str, object]:
    """纯函数式推演（I/O 只在 manifest 读取与 schema_migrations 查询）。"""
    if not manifest_path.strip():
        return _unavailable(
            "LUMIRSS_RELEASE_MANIFEST is not configured — no release manifest to preview."
        )
    manifest, error = _read_manifest(Path(manifest_path.strip()))
    if manifest is None:
        return _unavailable(error or "release manifest unavailable.")
    target_version = str(manifest["version"]).strip()
    min_compat_value = manifest.get("min_compat")
    min_compat = str(min_compat_value).strip() if isinstance(min_compat_value, str) and min_compat_value.strip() else None
    migrations_raw = manifest.get("migrations")
    target_migrations: list[str] = []
    migrations_known = isinstance(migrations_raw, list) and all(
        isinstance(m, str) for m in migrations_raw
    )
    if migrations_known:
        target_migrations = sorted({str(m).rsplit("/", 1)[-1] for m in migrations_raw})

    blocked_reason: str | None = None
    comparison = _compare_versions(target_version, current_version)
    if comparison == 0:
        blocked_reason = (
            f"Target version {target_version} equals the current version — nothing to upgrade."
        )
    elif comparison == -1:
        blocked_reason = (
            f"Target version {target_version} is OLDER than the current {current_version}."
            " Downgrades are not upgrades — use './lumirss rollback' instead."
        )

    new_migrations: list[str] = []
    applied: set[int] = set()
    if migrations_known:
        try:
            applied = _applied_migration_versions(control_db)
        except Exception:  # noqa: BLE001 — 控制库不可读 → 无法核实差异，如实阻断
            blocked_reason = blocked_reason or (
                "Could not read applied migrations from the control database."
            )
        if applied:
            target_versions = {
                v for m in target_migrations if (v := _migration_version(m)) is not None
            }
            ahead = sorted(applied - target_versions)
            if ahead and blocked_reason is None:
                blocked_reason = (
                    "The database is AHEAD of the target release"
                    f" (applied migration {ahead[0]:04d} missing from the manifest)."
                    " Upgrading would run old code on a newer schema."
                )
        new_migrations = [
            m
            for m in target_migrations
            if (v := _migration_version(m)) is not None and v not in applied
        ]

    return {
        "available": True,
        "reason": None,
        "currentVersion": current_version,
        "targetVersion": target_version,
        "newMigrations": new_migrations,
        "minCompat": min_compat,
        "blocked": blocked_reason is not None,
        "blockedReason": blocked_reason,
    }


def preview_response(**overrides: object) -> dict[str, object]:
    """稳定响应形状（字段恒在，缺省 None/[]）。"""
    base: dict[str, object] = {field: None for field in _PREVIEW_FIELDS}
    base["newMigrations"] = []
    base.update(overrides)
    return base
