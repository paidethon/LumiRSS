"""NEW-324 阅读批注 Markdown 输出 — 来源+稳定锚点、A/B 批注隔离、校验。"""



from new2xx_ab import ab_env, seed_entry  # noqa: F401 — pytest 夹具注册


def _add_annotation(client, headers, entry_ref, *, excerpt, note="", para="p1"):
    created = client.post(
        "/api/v1/annotations",
        json={
            "entryRef": entry_ref,
            "anchor": {"paraId": para, "prefix": "", "exact": excerpt, "suffix": ""},
            "excerpt": excerpt,
            "note": note,
            "color": "yellow",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text


def test_new324_export_contains_source_and_stable_anchors(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    entry_ref = seed_entry(ab_env, "a", "entry-324-1", title="注意力机制",
                           content_text="正文")
    _add_annotation(client, a, entry_ref, excerpt="关键句一", note="我的看法", para="para-abc")
    _add_annotation(client, a, entry_ref, excerpt="关键句二", para="para-def")

    exported = client.post(
        "/api/v1/annotations/markdown-export",
        json={"entryRefs": [entry_ref]},
        headers=a,
    )
    assert exported.status_code == 200, exported.text
    body = exported.json()
    assert body["entryCount"] == 1 and body["annotationCount"] == 2
    assert body["unresolvedRefs"] == []
    assert body["filename"].startswith("LumiRSS-批注-") and body["filename"].endswith(".md")
    content = body["content"]
    # 来源（标题 + 投影中的订阅源行 + 原文回跳）
    assert "## 注意力机制" in content
    assert "- 来源：源" in content
    assert f"/reader?entry={entry_ref}" in content
    # 稳定锚点（Obsidian 块 id + 服务端回跳链接）
    assert "^lumi-para-abc" in content and "^lumi-para-def" in content
    assert f"/reader?entry={entry_ref}&para=para-abc" in content
    assert "我的看法" in content
    # Lumi 不代写文件：诚实说明保存由用户完成
    assert "保存" in body["honestyNote"]

    # 台账可追溯
    history = client.get("/api/v1/annotations/markdown-export", headers=a).json()
    assert len(history["exports"]) == 1
    assert history["exports"][0]["annotationCount"] == 2


def test_new324_unresolved_refs_listed_honestly(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    entry_ref = seed_entry(ab_env, "a", "entry-324-2", title="t")
    _add_annotation(client, a, entry_ref, excerpt="e1")
    body = client.post(
        "/api/v1/annotations/markdown-export",
        json={"entryRefs": [entry_ref, "rss:unknown-entry-324"]},
        headers=a,
    ).json()
    assert body["unresolvedRefs"] == ["rss:unknown-entry-324"]
    assert body["entryCount"] == 1
    # 全部未知 → 400（诚实拒绝，不产出空文件）
    only_unknown = client.post(
        "/api/v1/annotations/markdown-export",
        json={"entryRefs": ["rss:unknown-entry-324"]},
        headers=a,
    )
    assert only_unknown.status_code == 400
    # 空 / 超限 → 400
    assert (
        client.post(
            "/api/v1/annotations/markdown-export", json={"entryRefs": []}, headers=a
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/annotations/markdown-export",
            json={"entryRefs": [f"rss:x{i}" for i in range(51)]},
            headers=a,
        ).status_code
        == 400
    )


def test_new324_per_user_isolation_between_accounts(ab_env):  # noqa: F811
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    ref_a = seed_entry(ab_env, "a", "entry-324-a", title="A 的文章")
    _add_annotation(client, a, ref_a, excerpt="A 的批注内容", para="pa")
    # B 在自己的库里对同一 entryRef 建批注（per-user 库天然隔离）
    seed_entry(ab_env, "b", "entry-324-a", title="B 眼中的文章")
    _add_annotation(client, b, ref_a, excerpt="B 的批注内容", para="pb")

    body_a = client.post(
        "/api/v1/annotations/markdown-export",
        json={"entryRefs": [ref_a]},
        headers=a,
    ).json()
    assert "A 的批注内容" in body_a["content"]
    assert "B 的批注内容" not in body_a["content"]

    body_b = client.post(
        "/api/v1/annotations/markdown-export",
        json={"entryRefs": [ref_a]},
        headers=b,
    ).json()
    assert "B 的批注内容" in body_b["content"]
    assert "A 的批注内容" not in body_b["content"]
    assert body_b["annotationCount"] == 1

    # 台账互不可见
    assert len(client.get("/api/v1/annotations/markdown-export", headers=a).json()["exports"]) == 1
    assert len(client.get("/api/v1/annotations/markdown-export", headers=b).json()["exports"]) == 1
