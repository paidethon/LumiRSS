"""N196 升级任务进度 — 读取 ./lumirss update 写入的阶段 JSON。

契约（lumirss 脚本侧写入，本模块只读）：
- 路径来自 LUMIRSS_DEPLOY_STATUS_FILE；未配置 → ``available: false``
  （诚实：不是「没有升级」，而是「没有配置进度上报」）；
- 文件不存在 → available:false + 「尚无升级记录」；
- 解析失败 / schema 不符 → available:false + 原因（绝不把坏文件
  硬塞给管理台渲染）；
- 内容原样透传（脚本只写阶段名/状态/时间戳/imageTag——绝无秘密）；
  本模块不做二次加工，避免两处定义漂移。
"""

import json
from pathlib import Path

DEPLOY_STATUS_SCHEMA = "lumirss-deploy-status/v1"
_MAX_STATUS_BYTES = 64 * 1024


def read_deploy_status(path_value: str) -> dict[str, object]:
    """端点口径的只读读取（永不抛出）。"""
    if not path_value.strip():
        return {
            "available": False,
            "reason": "LUMIRSS_DEPLOY_STATUS_FILE is not configured — update progress is not reported.",
            "deploy": None,
        }
    path = Path(path_value.strip())
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {
            "available": False,
            "reason": "No update has run yet (status file not found).",
            "deploy": None,
        }
    if len(raw) > _MAX_STATUS_BYTES:
        return {
            "available": False,
            "reason": "Deploy status file is implausibly large — refusing to render it.",
            "deploy": None,
        }
    try:
        data = json.loads(raw)
    except ValueError:
        return {
            "available": False,
            "reason": "Deploy status file is not valid JSON.",
            "deploy": None,
        }
    if not isinstance(data, dict) or str(data.get("schema", "")) != DEPLOY_STATUS_SCHEMA:
        return {
            "available": False,
            "reason": f"Deploy status file schema mismatch (expected {DEPLOY_STATUS_SCHEMA}).",
            "deploy": None,
        }
    return {"available": True, "reason": None, "deploy": data}
