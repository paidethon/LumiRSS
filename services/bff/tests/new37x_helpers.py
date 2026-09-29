"""NEW-371..380 运行治理组共享测试助手（管理员作用域提权铸造）。"""

from new2xx_ab import PASSWORD  # noqa: F401 — 与 A/B 夹具同密码源


def mint_step_up(client, admin_headers: dict, operation: str) -> dict[str, str]:
    """为当前管理员铸造 (operation, 本人) 作用域的一次性提权头。

    FIX-218 契约：实例级敏感操作的 target = 操作管理员本人 id。"""
    session = client.get("/api/v1/auth/session", headers=admin_headers).json()
    owner_id = str(session["userId"])
    minted = client.post(
        "/api/v1/admin/step-up",
        headers=admin_headers,
        json={"password": PASSWORD, "operation": operation, "targetUserId": owner_id},
    )
    assert minted.status_code == 200, minted.text
    return {"X-Lumi-Step-Up": minted.json()["token"]}


def step_up_headers(client, admin_headers: dict, operation: str) -> dict:
    """合并 cookie 与提权头的便捷组合。"""
    return {**admin_headers, **mint_step_up(client, admin_headers, operation)}
