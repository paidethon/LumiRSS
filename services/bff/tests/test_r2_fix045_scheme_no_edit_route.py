"""FIX-045 — 邀请方案（模板）没有编辑路径：固定模板与实例的生命周期。

问题原型：「邀请模板编辑影响已发邀请且没有明确规则」。当前实现用
**不可变模板**直接消灭这个冲突面：

- 路由面只有 GET /admin/invite-schemes、POST /admin/invite-schemes、
  POST /admin/invite-schemes/{id}/generate-invites、DELETE
  /admin/invite-schemes/{id}——没有 PUT/PATCH，已发邀请不受模板后续
  变更影响（也不存在模板后续变更）；
- 批量生成（N001）产生互相独立的一次性邀请（token 独立、
  scheme_id 戳记；test_invite_schemes.
  test_batch_generation_independent_invites_stamped_with_scheme）；
- 删除模板在 UI 确认对话框明确规则：「只删除模板；已生成的邀请和
  已激活的账号保留其方案记录」；账户行保留 scheme_id + 名称投影。

本守卫经 OpenAPI 契约面钉定「无编辑路由」这一结构事实（对路由器
挂载方式不敏感）：未来若要给方案加编辑，必须先回答「已发邀请是否
跟随」并把规则写进确认 UI 与文档，同时更新本守卫。
"""

from lumirss.main import app


def _invite_scheme_operations() -> dict[str, set[str]]:
    """path → OpenAPI 操作方法集（只含 invite-schemes 相关路径）。"""
    paths = app.openapi().get("paths", {})
    return {
        path: {str(method).lower() for method in methods}
        for path, methods in paths.items()
        if "invite-schemes" in path
    }


def test_invite_scheme_routes_are_read_create_generate_delete_only():
    operations = _invite_scheme_operations()
    assert operations, "invite-schemes routes must exist"
    for path, methods in operations.items():
        assert methods <= {"get", "post", "delete"}, (
            f"invite-schemes 路由出现编辑动词: {sorted(methods)} {path}"
        )


def test_invite_scheme_has_no_put_or_patch_route():
    for path, methods in _invite_scheme_operations().items():
        assert "put" not in methods and "patch" not in methods, (
            f"方案模板不可编辑（FIX-045）：发现 {sorted(methods)} {path}"
        )


def test_generate_and_delete_paths_exist_per_contract():
    operations = _invite_scheme_operations()
    assert any(path.endswith("/invite-schemes") for path in operations), operations
    assert any("generate-invites" in path for path in operations), operations
    # {scheme_id} 上的 DELETE（删除模板本身）存在。
    assert any(
        "{scheme_id}" in path and "generate-invites" not in path for path in operations
    ), operations
