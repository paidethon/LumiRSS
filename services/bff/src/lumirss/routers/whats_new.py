"""N198 版本差异功能导览 — GET /api/v1/whats-new。

语义（诚实口径）：
- 数据源是随仓库 checked in 的 docs/release-notes.json（当前发布
  的功能清单，≤40 条）；文件缺失/损坏 → version:null + 空清单，
  前端据此完全隐藏导览卡，绝不编造条目；
- ``sinceVersion`` 已知（== 清单版本）→ 空清单（该设备已看过此版本）；
  未知/缺省 → 全部条目（「unknown version → all」——无法推演差异时
  宁可多展示，不静默吞掉新功能）；
- ``adminOnly`` 条目只对 owner/admin 出现（服务端角色过滤——成员端
  的响应里根本没有这些条目，不是前端隐藏）；
- 本端点只读，无任何写路径、无任何凭据材料。
"""

from fastapi import APIRouter, Query, Request

from lumirss.user_scope import principal_of
from lumirss.whats_new import load_release_notes

router = APIRouter()


@router.get("/api/v1/whats-new")
async def whats_new(
    request: Request,
    sinceVersion: str | None = Query(default=None, max_length=64),
) -> dict[str, object]:
    from lumirss.config import LumiSettings

    notes = load_release_notes(LumiSettings().LUMIRSS_RELEASE_NOTES)
    if notes is None:
        return {"version": None, "sinceVersion": sinceVersion, "features": []}
    principal = principal_of(request.scope)
    is_admin = principal is not None and principal.get("role") in ("owner", "admin")
    features = [
        feature
        for feature in notes["features"]
        if is_admin or not feature.get("adminOnly")
    ]
    version = notes["version"]
    # 已看过当前版本 → 空导览；未知/旧版本/缺省 → 全部（角色过滤后）。
    if sinceVersion is not None and version is not None and sinceVersion == version:
        features = []
    return {"version": version, "sinceVersion": sinceVersion, "features": features}
