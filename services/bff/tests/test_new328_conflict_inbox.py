"""NEW-328 库同步冲突收件箱 — 并排展示、显式二选一解决、A/B 隔离。"""


from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new321_vault import write_vault

NOTE_V1 = "---\ntitle: 原始标题\n---\n第一版正文。\n"
NOTE_V2 = "---\ntitle: 源更新后的标题\n---\n第二版正文，已被上游修改。\n"


def _setup(client, owner, tmp_path):
    vault = write_vault(tmp_path, {"a.md": NOTE_V1})
    created = client.put(
        "/api/v1/obsidian/settings", json={"vaultPath": str(vault)}, headers=owner
    )
    assert created.status_code == 200, created.text
    assert (
        client.post("/api/v1/obsidian/rescan", headers=owner).status_code == 200
    )
    from new321_vault import note_uuids

    return tmp_path / "vault", note_uuids(client, owner)["a.md"]


def test_new328_conflict_flow_keep_independent_and_adopt_source(ab_env, tmp_path):  # noqa: F811
    client, owner = ab_env["client"], ab_env["owner"]
    vault, note_uuid = _setup(client, owner, tmp_path)

    # 建立个人修正层（Lumi 侧独立层）
    put = client.put(
        "/api/v1/obsidian/conflict-inbox/corrections",
        json={"noteUuid": note_uuid, "personalTitle": "我的标题", "personalNote": "我的备注"},
        headers=owner,
    )
    assert put.status_code == 200, put.text

    # 源未变 → 检测不产生冲突
    detect = client.post("/api/v1/obsidian/conflict-inbox/detect", headers=owner).json()
    assert detect == {
        "checked": 1,
        "opened": 0,
        "refreshed": 0,
        "unchanged": 1,
        "honestyNote": detect["honestyNote"],
    }

    # 源文件更新（用户在 Obsidian 侧改文件）→ 重扫 → 检测出冲突
    (vault / "a.md").write_text(NOTE_V2, encoding="utf-8")
    assert (
        client.post("/api/v1/obsidian/rescan", headers=owner).status_code == 200
    )
    detect = client.post("/api/v1/obsidian/conflict-inbox/detect", headers=owner).json()
    assert detect["opened"] == 1

    inbox = client.get("/api/v1/obsidian/conflict-inbox", headers=owner).json()["conflicts"]
    assert len(inbox) == 1
    conflict = inbox[0]
    # 并排数据：源版本 vs 个人修正
    assert conflict["source"]["title"] == "源更新后的标题"
    assert "第二版正文" in conflict["source"]["excerpt"]
    assert conflict["personal"]["title"] == "我的标题"
    assert conflict["personal"]["note"] == "我的备注"
    assert conflict["currentContentHash"] != conflict["baseContentHash"]

    # 决定保留独立层：修正重定基到新源版本
    resolve = client.post(
        f"/api/v1/obsidian/conflict-inbox/{conflict['id']}/resolve",
        json={"decision": "keep_independent"},
        headers=owner,
    )
    assert resolve.status_code == 200, resolve.text
    assert resolve.json()["status"] == "kept_independent"
    corrections = client.get(
        "/api/v1/obsidian/conflict-inbox/corrections", headers=owner
    ).json()["corrections"]
    assert corrections[0]["stale"] is False  # 已重定基到当前源版本
    assert corrections[0]["personalTitle"] == "我的标题"
    assert client.get("/api/v1/obsidian/conflict-inbox", headers=owner).json()["conflicts"] == []

    # 源再次更新 → 又冲突 → 这次采用源版本（个人修正层删除）
    (vault / "a.md").write_text(NOTE_V2 + "第三版。\n", encoding="utf-8")
    client.post("/api/v1/obsidian/rescan", headers=owner)
    client.post("/api/v1/obsidian/conflict-inbox/detect", headers=owner)
    conflict = client.get(
        "/api/v1/obsidian/conflict-inbox", headers=owner
    ).json()["conflicts"][0]
    bad_decision = client.post(
        f"/api/v1/obsidian/conflict-inbox/{conflict['id']}/resolve",
        json={"decision": "coin_flip"},
        headers=owner,
    )
    assert bad_decision.status_code == 400
    resolve2 = client.post(
        f"/api/v1/obsidian/conflict-inbox/{conflict['id']}/resolve",
        json={"decision": "adopt_source"},
        headers=owner,
    )
    assert resolve2.status_code == 200
    assert resolve2.json()["status"] == "adopted_source"
    assert (
        client.get(
            "/api/v1/obsidian/conflict-inbox/corrections", headers=owner
        ).json()["corrections"]
        == []
    )
    # 已解决的冲突不可重复解决；历史留档
    assert (
        client.post(
            f"/api/v1/obsidian/conflict-inbox/{conflict['id']}/resolve",
            json={"decision": "adopt_source"},
            headers=owner,
        ).status_code
        == 400
    )
    history = client.get("/api/v1/obsidian/conflict-inbox/history", headers=owner).json()
    assert {h["status"] for h in history["history"]} == {"kept_independent", "adopted_source"}
    # 未知冲突 → 404
    assert (
        client.post(
            "/api/v1/obsidian/conflict-inbox/no-such/resolve",
            json={"decision": "adopt_source"},
            headers=owner,
        ).status_code
        == 404
    )


def test_new328_correction_validation(ab_env, tmp_path):  # noqa: F811
    client, owner = ab_env["client"], ab_env["owner"]
    _, note_uuid = _setup(client, owner, tmp_path)
    # 投影中不存在的笔记 → 404
    assert (
        client.put(
            "/api/v1/obsidian/conflict-inbox/corrections",
            json={"noteUuid": "no-such", "personalTitle": "x"},
            headers=owner,
        ).status_code
        == 404
    )
    # 全空修正 → 400
    assert (
        client.put(
            "/api/v1/obsidian/conflict-inbox/corrections",
            json={"noteUuid": note_uuid},
            headers=owner,
        ).status_code
        == 400
    )
    # 建一条有效修正，再显式删除修正层
    assert (
        client.put(
            "/api/v1/obsidian/conflict-inbox/corrections",
            json={"noteUuid": note_uuid, "personalTitle": "待删标题"},
            headers=owner,
        ).status_code
        == 200
    )
    # 显式删除修正层
    assert (
        client.delete(
            f"/api/v1/obsidian/conflict-inbox/corrections?noteUuid={note_uuid}",
            headers=owner,
        ).status_code
        == 200
    )
    # 再删 → 404（已不存在）
    assert (
        client.delete(
            f"/api/v1/obsidian/conflict-inbox/corrections?noteUuid={note_uuid}",
            headers=owner,
        ).status_code
        == 404
    )


def test_new328_per_user_isolation_between_accounts(ab_env, tmp_path):  # noqa: F811
    client, owner, b = ab_env["client"], ab_env["owner"], ab_env["b"]
    _, note_uuid = _setup(client, owner, tmp_path)
    assert (
        client.put(
            "/api/v1/obsidian/conflict-inbox/corrections",
            json={"noteUuid": note_uuid, "personalTitle": "我的标题"},
            headers=owner,
        ).status_code
        == 200
    )
    for method, path, kwargs in (
        ("get", "/api/v1/obsidian/conflict-inbox", {}),
        ("get", "/api/v1/obsidian/conflict-inbox/corrections", {}),
        ("post", "/api/v1/obsidian/conflict-inbox/detect", {}),
        (
            "put",
            "/api/v1/obsidian/conflict-inbox/corrections",
            {"json": {"noteUuid": note_uuid, "personalTitle": "B 的篡改"}},
        ),
    ):
        response = getattr(client, method)(path, headers=b, **kwargs)
        assert response.status_code == 403, (method, path, response.text)
    corrections = client.get(
        "/api/v1/obsidian/conflict-inbox/corrections", headers=owner
    ).json()["corrections"]
    assert corrections[0]["personalTitle"] == "我的标题"
