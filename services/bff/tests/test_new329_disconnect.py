"""NEW-329 本地资料断开连接 — 撤销授权停止扫描、副本去留显式二选一。"""


from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from test_new325_root_profiles import _create_root


def _scan(client, headers, root_id):
    return client.post(f"/api/v1/obsidian/roots/{root_id}/scan", headers=headers)


def test_new329_disconnect_stops_scan_and_user_decides_copies(ab_env, tmp_path):  # noqa: F811
    client, owner = ab_env["client"], ab_env["owner"]
    root = _create_root(
        client, owner, tmp_path, name="待断开的库",
        files={"a.md": "内容甲", "b.md": "内容乙"}, root_name="root-dc",
    )
    assert _scan(client, owner, root["id"]).json()["added"] == 2

    # 撤销授权 → 扫描入口校验授权状态并拒绝（副本原样保留、可读）
    disconnected = client.post(
        f"/api/v1/obsidian/roots/{root['id']}/disconnect", headers=owner
    )
    assert disconnected.status_code == 200, disconnected.text
    assert disconnected.json()["authorized"] is False
    assert disconnected.json()["copiesPolicy"] == ""  # 副本去留尚未决定
    refused = _scan(client, owner, root["id"])
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["type"] == "root_not_authorized"
    notes = client.get(f"/api/v1/obsidian/roots/{root['id']}/notes", headers=owner).json()
    assert len(notes["notes"]) == 2  # 未决定前副本原样保留

    # 用户显式选择：删除本应用副本（只清 Lumi 侧，绝不触碰源目录）
    decided = client.post(
        f"/api/v1/obsidian/roots/{root['id']}/copies",
        json={"action": "delete"},
        headers=owner,
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["copiesPolicy"] == "deleted"
    assert decided.json()["removedCopies"] == 2
    notes = client.get(f"/api/v1/obsidian/roots/{root['id']}/notes", headers=owner).json()
    assert notes["notes"] == []
    assert (tmp_path / "root-dc" / "a.md").read_text(encoding="utf-8") == "内容甲"
    # 删除后扫描仍被拒（授权未恢复）
    assert _scan(client, owner, root["id"]).status_code == 409

    # 重新授权 → 扫描恢复；副本已被删 → 如实全新导入
    reconnected = client.post(
        f"/api/v1/obsidian/roots/{root['id']}/reconnect", headers=owner
    )
    assert reconnected.status_code == 200
    assert reconnected.json()["authorized"] is True
    rescanned = _scan(client, owner, root["id"])
    assert rescanned.status_code == 200
    assert rescanned.json()["added"] == 2


def test_new329_keep_copies_choice(ab_env, tmp_path):  # noqa: F811
    client, owner = ab_env["client"], ab_env["owner"]
    root = _create_root(
        client, owner, tmp_path, name="保留副本的库",
        files={"a.md": "内容"}, root_name="root-keep",
    )
    assert _scan(client, owner, root["id"]).json()["added"] == 1
    client.post(f"/api/v1/obsidian/roots/{root['id']}/disconnect", headers=owner)
    kept = client.post(
        f"/api/v1/obsidian/roots/{root['id']}/copies", json={"action": "keep"}, headers=owner
    )
    assert kept.status_code == 200
    assert kept.json()["copiesPolicy"] == "kept"
    assert kept.json()["removedCopies"] == 0  # 保留 = 不删除
    notes = client.get(f"/api/v1/obsidian/roots/{root['id']}/notes", headers=owner).json()
    assert len(notes["notes"]) == 1  # 导入副本仍在（只读可见）
    # 无效动作 → 400；未知根 → 404
    assert (
        client.post(
            f"/api/v1/obsidian/roots/{root['id']}/copies",
            json={"action": "purge"},
            headers=owner,
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/obsidian/roots/no-such/copies",
            json={"action": "keep"},
            headers=owner,
        ).status_code
        == 404
    )


def test_new329_per_user_isolation_between_accounts(ab_env, tmp_path):  # noqa: F811
    client, owner, b = ab_env["client"], ab_env["owner"], ab_env["b"]
    root = _create_root(
        client, owner, tmp_path, name="A 的库",
        files={"a.md": "内容"}, root_name="root-iso",
    )
    for path, kwargs in (
        (f"/api/v1/obsidian/roots/{root['id']}/disconnect", {}),
        (f"/api/v1/obsidian/roots/{root['id']}/copies", {"json": {"action": "delete"}}),
        (f"/api/v1/obsidian/roots/{root['id']}/reconnect", {}),
    ):
        response = client.post(path, headers=b, **kwargs)
        assert response.status_code == 403, (path, response.text)
    profile = client.get(f"/api/v1/obsidian/roots/{root['id']}", headers=owner).json()
    assert profile["authorized"] is True  # B 的动作全部无效
    assert _scan(client, owner, root["id"]).status_code == 200
