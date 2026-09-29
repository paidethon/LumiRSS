"""NEW-378 实例功能依赖图 — 未探测如实 unknown；本地探测（零网络）
落实际探测时间；秘密只有状态位。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册


def test_new378_graph_unprobed_is_unknown(ab_env):  # noqa: F811
    """未探测前：依赖状态如实 unknown；member 403。"""
    client = ab_env["client"]
    owner = ab_env["owner"]

    denied = client.get("/api/v1/admin/feature-dependencies", headers=ab_env["b"])
    assert denied.status_code == 403

    graph = client.get("/api/v1/admin/feature-dependencies", headers=owner)
    assert graph.status_code == 200, graph.text
    payload = graph.json()
    keys = {feature["key"] for feature in payload["features"]}
    assert {"native_rss", "rsshub_sources", "mail_digest", "rag_semantic"} <= keys
    native = next(f for f in payload["features"] if f["key"] == "native_rss")
    assert all(dep["status"] == "unknown" for dep in native["deps"])
    assert native["ready"] is False
    assert any("unknown" in note or "未探测" in note for note in payload["notes"])


def test_new378_probe_records_real_time(ab_env):  # noqa: F811
    """探测后：每个依赖项有实际探测时间（本轮生成）；sqlite 配置为真，
    rsshub/webhook/绑定在测试实例如实缺失。"""
    client = ab_env["client"]
    owner = ab_env["owner"]

    probed = client.post("/api/v1/admin/feature-dependencies/probe", headers=owner)
    assert probed.status_code == 200, probed.text
    payload = probed.json()

    deps: dict[str, dict] = {}
    for feature in payload["features"]:
        for dep in feature["deps"]:
            deps[dep["key"]] = dep
    assert deps["sqlite"]["status"] == "configured"
    assert deps["sqlite"]["probedAt"]
    assert deps["rsshub_url"]["status"] == "missing"
    assert deps["webhook_signing_key"]["status"] == "missing"
    assert deps["freshrss_binding"]["status"] == "missing"
    assert deps["rsshub_url"]["probedAt"] == deps["sqlite"]["probedAt"]

    # 只读图现在拿到最新态 + 探测时间。
    graph = client.get("/api/v1/admin/feature-dependencies", headers=owner).json()
    native = next(f for f in graph["features"] if f["key"] == "native_rss")
    assert native["deps"][0]["status"] == "configured"
    assert native["deps"][0]["probedAt"]
    assert native["ready"] is False  # FreshRSS 绑定仍缺


def test_new378_obsidian_probe_respects_env(ab_env, monkeypatch, tmp_path):  # noqa: F811
    """配置仓库目录后探测 → obsidian_vault configured True。"""
    client = ab_env["client"]
    owner = ab_env["owner"]
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("LUMIRSS_OBSIDIAN_VAULT_DIR", str(vault))

    payload = client.post("/api/v1/admin/feature-dependencies/probe", headers=owner).json()
    deps = {
        dep["key"]: dep
        for feature in payload["features"]
        for dep in feature["deps"]
    }
    assert deps["obsidian_vault"]["status"] == "configured"


def test_new378_no_secret_values_in_response(ab_env):  # noqa: F811
    """秘密只有状态位：探测/图响应绝不包含密钥值形态。"""
    import inspect

    client = ab_env["client"]
    owner = ab_env["owner"]
    graph = client.get("/api/v1/admin/feature-dependencies", headers=owner)
    assert "sk-" not in graph.text
    assert "password" not in graph.text.lower()

    # 结构钉定：本组模块不读秘密值（只查 configured/存在性）。
    from lumirss import new378_feature_deps as mod

    source = inspect.getsource(mod)
    assert ".get(" in source  # 有读取
    assert "secrets.get(\"freshrss_pool:" not in source
