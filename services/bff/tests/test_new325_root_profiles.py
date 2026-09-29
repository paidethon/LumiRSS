"""NEW-325 资料库多根目录档案 — 独立只读档案、忽略规则、各自同步状态。"""


from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册


def _create_root(client, headers, tmp_path, *, name, files, ignore=None, root_name=None):
    vault = write_root(tmp_path, files, root_name=root_name or name)
    payload = {"label": name, "rootPath": str(vault)}
    if ignore is not None:
        payload["ignoreGlobs"] = ignore
    created = client.post("/api/v1/obsidian/roots", json=payload, headers=headers)
    assert created.status_code == 201, created.text
    return created.json()


def write_root(tmp_path, files, *, root_name):

    root = tmp_path / root_name
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def test_new325_independent_profiles_with_ignore_rules(ab_env, tmp_path):  # noqa: F811
    client, owner = ab_env["client"], ab_env["owner"]
    root1 = _create_root(
        client,
        owner,
        tmp_path,
        name="研究库",
        files={
            "papers/深度学习.md": "---\ntitle: 深度学习\ntags: [ai]\n---\n正文",
            "archive/旧笔记.md": "---\ntitle: 旧\n---\n旧内容",
        },
        ignore=["archive/*"],
        root_name="root-research",
    )
    root2 = _create_root(
        client,
        owner,
        tmp_path,
        name="日记库",
        files={"2026/日记.md": "---\ntitle: 日记\n---\n内容"},
        root_name="root-diary",
    )

    # 各自独立扫描：root1 忽略 archive（只收 1 条）；root2 收 1 条
    scan1 = client.post(f"/api/v1/obsidian/roots/{root1['id']}/scan", headers=owner)
    assert scan1.status_code == 200, scan1.text
    assert scan1.json()["added"] == 1
    scan2 = client.post(f"/api/v1/obsidian/roots/{root2['id']}/scan", headers=owner)
    assert scan2.json()["added"] == 1

    # 档案列表：各自同步状态（lastScanAt / noteCount / authorized）
    roots = client.get("/api/v1/obsidian/roots", headers=owner).json()["roots"]
    by_label = {r["label"]: r for r in roots}
    assert by_label["研究库"]["noteCount"] == 1
    assert by_label["日记库"]["noteCount"] == 1
    assert by_label["研究库"]["authorized"] is True
    assert by_label["研究库"]["lastScanAt"] is not None
    assert by_label["研究库"]["ignoreGlobs"] == ["archive/*"]

    # 笔记列表按根隔离；忽略规则内的文件不在档案中
    notes1 = client.get(f"/api/v1/obsidian/roots/{root1['id']}/notes", headers=owner).json()
    assert [n["relPath"] for n in notes1["notes"]] == ["papers/深度学习.md"]
    tagged = client.get(
        f"/api/v1/obsidian/roots/{root1['id']}/notes?tag=ai", headers=owner
    ).json()
    assert len(tagged["notes"]) == 1

    # 增量：改一 + 增一 → changed 1 / added 1；再次扫描 unchanged
    (tmp_path / "root-research" / "papers" / "深度学习.md").write_text(
        "---\ntitle: 深度学习\ntags: [ai]\n---\n更新正文", encoding="utf-8"
    )
    (tmp_path / "root-research" / "papers" / "新论文.md").write_text(
        "---\ntitle: 新论文\n---\n新", encoding="utf-8"
    )
    scan_again = client.post(f"/api/v1/obsidian/roots/{root1['id']}/scan", headers=owner).json()
    assert scan_again["changed"] == 1 and scan_again["added"] == 1
    third = client.post(f"/api/v1/obsidian/roots/{root1['id']}/scan", headers=owner).json()
    assert third["unchanged"] == 2 and third["added"] == 0

    # PATCH 忽略规则 + 校验
    patched = client.patch(
        f"/api/v1/obsidian/roots/{root1['id']}",
        json={"ignoreGlobs": ["archive/*", "drafts/"]},
        headers=owner,
    )
    assert patched.status_code == 200
    assert patched.json()["ignoreGlobs"] == ["archive/*", "drafts/"]
    bad = client.post(
        "/api/v1/obsidian/roots",
        json={"label": "坏根", "rootPath": str(tmp_path / "no-such-dir-325")},
        headers=owner,
    )
    assert bad.status_code == 503  # Vault 不可达（与主 Vault 同口径）
    empty_label = client.post(
        "/api/v1/obsidian/roots",
        json={"label": "", "rootPath": str(tmp_path)},
        headers=owner,
    )
    assert empty_label.status_code == 400

    # DELETE 收敛（档案 + 笔记行级联）
    assert (
        client.delete(f"/api/v1/obsidian/roots/{root2['id']}", headers=owner).status_code
        == 204
    )
    assert (
        client.get(f"/api/v1/obsidian/roots/{root2['id']}", headers=owner).status_code
        == 404
    )


def test_new325_unreachable_root_scan_records_error_honestly(ab_env, tmp_path):  # noqa: F811
    client, owner = ab_env["client"], ab_env["owner"]
    root = _create_root(
        client, owner, tmp_path, name="会消失的库",
        files={"a.md": "内容"}, root_name="root-vanish",
    )
    assert client.post(f"/api/v1/obsidian/roots/{root['id']}/scan", headers=owner).status_code == 200
    import shutil

    shutil.rmtree(tmp_path / "root-vanish")
    gone = client.post(f"/api/v1/obsidian/roots/{root['id']}/scan", headers=owner)
    assert gone.status_code == 503
    profile = client.get(f"/api/v1/obsidian/roots/{root['id']}", headers=owner).json()
    assert profile["lastError"]  # 诚实记录


def test_new325_per_user_isolation_between_accounts(ab_env, tmp_path):  # noqa: F811
    client, owner, b = ab_env["client"], ab_env["owner"], ab_env["b"]
    root = _create_root(
        client, owner, tmp_path, name="私有库",
        files={"a.md": "内容"}, root_name="root-private",
    )
    for method, path, kwargs in (
        ("get", "/api/v1/obsidian/roots", {}),
        ("get", f"/api/v1/obsidian/roots/{root['id']}", {}),
        ("post", f"/api/v1/obsidian/roots/{root['id']}/scan", {}),
        (
            "post",
            "/api/v1/obsidian/roots",
            {"json": {"label": "B 的根", "rootPath": str(tmp_path)}},
        ),
    ):
        response = getattr(client, method)(path, headers=b, **kwargs)
        assert response.status_code == 403, (method, path, response.text)
    roots = client.get("/api/v1/obsidian/roots", headers=owner).json()["roots"]
    assert len(roots) == 1 and roots[0]["label"] == "私有库"
