"""N198 版本差异功能导览 — release-notes.json 的只读加载与路径发现。

数据文件 docs/release-notes.json（随仓库 checked in，发布时更新）::

    {"version": "0.2.0", "features": [{"id", "title", "entry", "adminOnly"?}]}

路径解析顺序（全部只读，找不到 → None，端点如实返回空导览）：
1. ``LUMIRSS_RELEASE_NOTES`` 显式覆盖（生产容器挂载点）；
2. 包内同名文件（未来镜像打包位，显式放置才生效）；
3. 从包位置向上找 ``docs/release-notes.json``（dev checkout 直接命中）。

结构容错：坏 JSON / 缺 version / features 非列表 → (None, [])——
导览是锦上添花，任何文件问题都不允许弄脏主阅读路径。
"""

import json
from pathlib import Path

_MAX_FEATURES = 40


def _candidate_paths(override: str) -> list[Path]:
    """显式覆盖 = 只用该路径（坏文件如实为空，绝不静默回退到别的来源）；
    未设置时按包内 → 仓库 docs 的顺序发现。"""
    if override.strip():
        return [Path(override.strip())]
    candidates: list[Path] = []
    package_sibling = Path(__file__).resolve().parent / "release_notes.json"
    candidates.append(package_sibling)
    here = Path(__file__).resolve().parent
    for parent in [here, *here.parents][:6]:
        candidates.append(parent / "docs" / "release-notes.json")
    return candidates


def _clean_features(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        return []
    features: list[dict[str, object]] = []
    for item in raw[:_MAX_FEATURES]:
        if not isinstance(item, dict):
            continue
        feature_id = str(item.get("id", "")).strip()
        title = str(item.get("title", "")).strip()
        if not feature_id or not title:
            continue
        entry_value = item.get("entry")
        feature: dict[str, object] = {
            "id": feature_id,
            "title": title,
            "entry": str(entry_value).strip() if isinstance(entry_value, str) else "",
        }
        if item.get("adminOnly") is True:
            feature["adminOnly"] = True
        features.append(feature)
    return features


def load_release_notes(override: str) -> dict[str, object] | None:
    """读取并容错解析；返回 {"version": str|None, "features": [...]} 或 None。"""
    for candidate in _candidate_paths(override):
        try:
            raw = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        version = str(data.get("version", "")).strip() or None
        return {"version": version, "features": _clean_features(data.get("features"))}
    return None
