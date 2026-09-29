"""NEW-323 笔记增量同步审批 — 预览零写入、确认后更新镜像、绝不写原库。"""



from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new321_vault import NOTE_A, NOTE_B, write_vault


def _connect(client, owner, tmp_path):
    vault = write_vault(
        tmp_path,
        {
            "AI/注意力机制.md": NOTE_A,
            "AI/transformer.md": NOTE_B,
        },
    )
    created = client.put(
        "/api/v1/obsidian/settings", json={"vaultPath": str(vault)}, headers=owner
    )
    assert created.status_code == 200, created.text


def _note_count(client, headers) -> int:
    status = client.get("/api/v1/obsidian/status", headers=headers).json()
    return int(status["noteCount"])


def test_new323_preview_lists_real_diff_without_touching_mirror(ab_env, tmp_path):  # noqa: F811
    client, owner = ab_env["client"], ab_env["owner"]
    _connect(client, owner, tmp_path)
    assert _note_count(client, owner) == 0  # 镜像为空（从未同步）

    preview = client.post("/api/v1/obsidian/sync/preview", headers=owner)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["status"] == "pending" and body["id"]
    assert body["added"] == 2
    assert sorted(body["files"]["added"]["items"]) == [
        "AI/transformer.md",
        "AI/注意力机制.md",
    ]
    # 关键断言：预览零写入——镜像在确认前绝不更新
    assert _note_count(client, owner) == 0

    # 确认 → 更新镜像（唯一写路径）
    applied = client.post(
        "/api/v1/obsidian/sync/apply", json={"approvalId": body["id"]}, headers=owner
    )
    assert applied.status_code == 200, applied.text
    report = applied.json()
    assert report["status"] == "applied" and report["report"]["added"] == 2
    assert _note_count(client, owner) == 2

    # 幂等防线：同一审批不能应用两次；未知审批 404
    replay = client.post(
        "/api/v1/obsidian/sync/apply", json={"approvalId": body["id"]}, headers=owner
    )
    assert replay.status_code == 409
    missing = client.post(
        "/api/v1/obsidian/sync/apply", json={"approvalId": "no-such"}, headers=owner
    )
    assert missing.status_code == 404
    empty = client.post("/api/v1/obsidian/sync/apply", json={}, headers=owner)
    assert empty.status_code == 400


def test_new323_incremental_diff_added_changed_removed(ab_env, tmp_path):  # noqa: F811
    client, owner = ab_env["client"], ab_env["owner"]
    _connect(client, owner, tmp_path)
    first = client.post("/api/v1/obsidian/sync/preview", headers=owner).json()
    client.post("/api/v1/obsidian/sync/apply", json={"approvalId": first["id"]}, headers=owner)

    # 源库演进：改一、增一、删一（无固定日历日期）
    vault = tmp_path / "vault"
    (vault / "AI" / "transformer.md").write_text(
        NOTE_B + "更新段落。\n", encoding="utf-8"
    )
    (vault / "AI" / "new-note.md").write_text(
        "---\ntitle: 新笔记\n---\n新内容\n", encoding="utf-8"
    )
    (vault / "AI" / "注意力机制.md").unlink()

    preview = client.post("/api/v1/obsidian/sync/preview", headers=owner).json()
    assert preview["added"] == 1 and preview["changed"] == 1 and preview["removed"] == 1
    assert preview["files"]["removed"]["items"] == ["AI/注意力机制.md"]

    # 新预览落库 → 旧 pending 自动 superseded（陈旧计划不可再执行）
    approvals = client.get("/api/v1/obsidian/sync/approvals", headers=owner).json()
    statuses = {a["id"]: a["status"] for a in approvals["approvals"]}
    assert statuses[first["id"]] == "applied"
    assert statuses[preview["id"]] == "pending"
    assert all(s != "pending" for k, s in statuses.items() if k != preview["id"])

    applied = client.post(
        "/api/v1/obsidian/sync/apply", json={"approvalId": preview["id"]}, headers=owner
    )
    assert applied.status_code == 200
    assert applied.json()["report"]["removed"] == 1
    assert _note_count(client, owner) == 2

    # 台账如实并存预览与实际报告
    ledger = client.get("/api/v1/obsidian/sync/approvals", headers=owner).json()
    row = next(a for a in ledger["approvals"] if a["id"] == preview["id"])
    assert row["planned"]["added"] == 1
    assert row["appliedReport"]["added"] == 1


def test_new323_vault_stays_read_only_after_sync(ab_env, tmp_path):  # noqa: F811
    client, owner = ab_env["client"], ab_env["owner"]
    _connect(client, owner, tmp_path)
    preview = client.post("/api/v1/obsidian/sync/preview", headers=owner).json()
    client.post("/api/v1/obsidian/sync/apply", json={"approvalId": preview["id"]}, headers=owner)
    # 原库文件字节未动（同步只更新 Lumi 侧镜像）
    assert (tmp_path / "vault" / "AI" / "注意力机制.md").read_text(encoding="utf-8") == NOTE_A
    assert (tmp_path / "vault" / "AI" / "transformer.md").read_text(encoding="utf-8") == NOTE_B


def test_new323_per_user_isolation_between_accounts(ab_env, tmp_path):  # noqa: F811
    client, owner, b = ab_env["client"], ab_env["owner"], ab_env["b"]
    _connect(client, owner, tmp_path)
    preview = client.post("/api/v1/obsidian/sync/preview", headers=owner).json()
    # B 不能预览 / 应用 / 看台账
    assert client.post("/api/v1/obsidian/sync/preview", headers=b).status_code == 403
    assert (
        client.post(
            "/api/v1/obsidian/sync/apply",
            json={"approvalId": preview["id"]},
            headers=b,
        ).status_code
        == 403
    )
    assert client.get("/api/v1/obsidian/sync/approvals", headers=b).status_code == 403
    # A 的审批还在 pending，A 自己仍能应用
    assert _note_count(client, owner) == 0
    applied = client.post(
        "/api/v1/obsidian/sync/apply", json={"approvalId": preview["id"]}, headers=owner
    )
    assert applied.status_code == 200
    assert _note_count(client, owner) == 2
