"""NEW-321 Obsidian 标签映射规则 — 预览层级/合并/冲突、物化导入层、A/B 隔离。"""


from lumirss.new321_tag_mapping import build_preview
from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new321_vault import write_vault


def _setup(client, owner, tmp_path):
    vault = write_vault(
        tmp_path,
        {
            "a.md": "---\ntitle: A\ntags: [ai, 深度学习]\n---\nA\n",
            "b.md": "---\ntitle: B\ntags: [ai]\n---\nB\n",
            "c.md": "---\ntitle: C\ntags: [tech]\n---\nC\n",
            "d.md": "---\ntitle: D\ntags: [ml]\n---\nD\n",
        },
    )
    created = client.put(
        "/api/v1/obsidian/settings", json={"vaultPath": str(vault)}, headers=owner
    )
    assert created.status_code == 200, created.text
    assert (
        client.post("/api/v1/obsidian/rescan", headers=owner).status_code == 200
    )


def test_new321_preview_shows_mapping_hierarchy_and_conflicts(ab_env, tmp_path):  # noqa: F811
    client, owner = ab_env["client"], ab_env["owner"]
    _setup(client, owner, tmp_path)

    # 无规则 → 全部恒等映射
    body = client.get("/api/v1/obsidian/tag-mapping/preview", headers=owner).json()
    assert body["sourceTags"] == ["ai", "ml", "tech", "深度学习"]
    assert all(not m["mapped"] for m in body["mappings"])

    # 规则：ai 与 深度学习 都映射到 tech/人工智能（层级：隐含父级 tech；
    # 两条规则汇入同一目标 → 合并）；ml → tech（目标 tech 是【没有规则】
    # 的源标签名 → 冲突：两个不同源标签的笔记会收敛到同一处）
    for source, target in (
        ("ai", "tech/人工智能"),
        ("深度学习", "tech/人工智能"),
        ("ml", "tech"),
    ):
        put = client.put(
            "/api/v1/obsidian/tag-mapping/rules",
            json={"sourceTag": source, "targetTag": target},
            headers=owner,
        )
        assert put.status_code == 200, put.text

    body = client.get("/api/v1/obsidian/tag-mapping/preview", headers=owner).json()
    mapped = {m["sourceTag"]: m["targetTag"] for m in body["mappings"]}
    assert mapped == {
        "ai": "tech/人工智能",
        "ml": "tech",
        "tech": "tech",
        "深度学习": "tech/人工智能",
    }
    assert body["hierarchy"]["ai"] == ["tech"]
    conflicts = [
        c for c in body["conflicts"] if c["kind"] == "target_is_source_tag"
    ]
    assert conflicts and conflicts[0]["sourceTag"] == "ml"
    merges = {m["targetTag"]: m["sourceTags"] for m in body["merges"]}
    assert merges["tech/人工智能"] == ["ai", "深度学习"]  # 两条规则汇入同一目标

    # 纯函数补一类冲突：目标嵌套在自身之下（成环）
    pure = build_preview(["a"], {"a": "a/b"})
    assert any(c["kind"] == "self_nesting" for c in pure["conflicts"])


def test_new321_materialize_builds_import_layer_only(ab_env, tmp_path):  # noqa: F811
    client, owner = ab_env["client"], ab_env["owner"]
    _setup(client, owner, tmp_path)
    assert (
        client.put(
            "/api/v1/obsidian/tag-mapping/rules",
            json={"sourceTag": "ai", "targetTag": "tech/人工智能"},
            headers=owner,
        ).status_code
        == 200
    )
    done = client.post("/api/v1/obsidian/tag-mapping/materialize", headers=owner)
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["notesTagged"] == 4  # 4 篇笔记都有标签（未映射的也如实进导入层）
    assert body["rulesApplied"] == 1

    # 导入层可查：个人标签计数 + 按个人标签找笔记
    overview = client.get("/api/v1/obsidian/tag-mapping/import", headers=owner).json()
    tags = {t["tag"]: t["count"] for t in overview["tags"]}
    assert tags["tech/人工智能"] == 2
    assert tags["深度学习"] == 1  # 未映射源标签原样进入导入层
    assert tags["tech"] == 1 and tags["ml"] == 1
    notes = client.get(
        "/api/v1/obsidian/tag-mapping/import?tag=tech%2F%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD",
        headers=owner,
    ).json()
    assert {n["title"] for n in notes["notes"]} == {"A", "B"}

    # 只改变导入层：源库标签原样保留（投影未动）
    listing = client.get("/api/v1/obsidian/notes?limit=50", headers=owner).json()
    note_a = next(n for n in listing["items"] if n["title"] == "A")
    assert "ai" in note_a["tags"] and "tech/人工智能" not in note_a["tags"]

    # 删除规则后重建导入层 → 个人标签随之消失
    deleted = client.delete(
        "/api/v1/obsidian/tag-mapping/rules?sourceTag=ai", headers=owner
    )
    assert deleted.status_code == 200
    client.post("/api/v1/obsidian/tag-mapping/materialize", headers=owner)
    overview = client.get("/api/v1/obsidian/tag-mapping/import", headers=owner).json()
    assert all(t["tag"] != "tech/人工智能" for t in overview["tags"])

    # 404：删除不存在的规则
    assert (
        client.delete(
            "/api/v1/obsidian/tag-mapping/rules?sourceTag=nope", headers=owner
        ).status_code
        == 404
    )


def test_new321_rule_validation_rejected_400(ab_env, tmp_path):  # noqa: F811
    client, owner = ab_env["client"], ab_env["owner"]
    _setup(client, owner, tmp_path)
    for payload in (
        {"sourceTag": "", "targetTag": "x"},
        {"sourceTag": "ai", "targetTag": ""},
        {"sourceTag": "ai", "targetTag": "a//b"},
        {"sourceTag": "ai", "targetTag": "/lead"},
        {"sourceTag": "x" * 60, "targetTag": "y"},
    ):
        bad = client.put(
            "/api/v1/obsidian/tag-mapping/rules", json=payload, headers=owner
        )
        assert bad.status_code == 400, payload
        assert bad.json()["error"]["type"] == "invalid_tag_mapping"


def test_new321_per_user_isolation_between_accounts(ab_env, tmp_path):  # noqa: F811
    client, owner, b = ab_env["client"], ab_env["owner"], ab_env["b"]
    _setup(client, owner, tmp_path)
    assert (
        client.put(
            "/api/v1/obsidian/tag-mapping/rules",
            json={"sourceTag": "ai", "targetTag": "tech/人工智能"},
            headers=owner,
        ).status_code
        == 200
    )
    # 成员 B：预览 / 规则 / 物化 / 导入层全部 403（Vault 是 owner 的扫描面）
    for method, path, kwargs in (
        ("get", "/api/v1/obsidian/tag-mapping/preview", {}),
        ("get", "/api/v1/obsidian/tag-mapping/rules", {}),
        (
            "put",
            "/api/v1/obsidian/tag-mapping/rules",
            {"json": {"sourceTag": "ai", "targetTag": "x"}},
        ),
        ("post", "/api/v1/obsidian/tag-mapping/materialize", {}),
        ("get", "/api/v1/obsidian/tag-mapping/import", {}),
    ):
        response = getattr(client, method)(path, headers=b, **kwargs)
        assert response.status_code == 403, (method, path, response.text)
    # owner 的规则不受影响
    rules = client.get("/api/v1/obsidian/tag-mapping/rules", headers=owner).json()
    assert len(rules["rules"]) == 1
