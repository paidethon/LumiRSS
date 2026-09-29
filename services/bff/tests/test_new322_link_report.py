"""NEW-322 链接解析报告 — 明确/歧义/失效分类、逐项纠正导入映射、A/B 隔离。"""


from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new321_vault import DUP_ONE, DUP_TWO, NOTE_A, NOTE_B, write_vault


def _setup(client, owner, tmp_path):
    vault = write_vault(
        tmp_path,
        {
            "AI/注意力机制.md": NOTE_A,
            "AI/transformer.md": NOTE_B,
            "docs/dup.md": DUP_ONE,
            "other/dup.md": DUP_TWO,
        },
    )
    created = client.put(
        "/api/v1/obsidian/settings", json={"vaultPath": str(vault)}, headers=owner
    )
    assert created.status_code == 200, created.text
    assert (
        client.post("/api/v1/obsidian/rescan", headers=owner).status_code == 200
    )
    from new321_vault import note_uuids

    return note_uuids(client, owner)


def test_new322_report_classifies_resolved_ambiguous_broken(ab_env, tmp_path):  # noqa: F811
    client, owner = ab_env["client"], ab_env["owner"]
    uuids = _setup(client, owner, tmp_path)
    note_a = uuids["AI/注意力机制.md"]

    report = client.post(
        "/api/v1/obsidian/link-report", json={}, headers=owner
    ).json()
    assert report["truncated"] is False
    items = {item["raw"]: item for item in report["items"] if item["noteUuid"] == note_a}
    # transformer → 唯一候选 → resolved
    assert items["transformer"]["status"] == "resolved"
    assert items["transformer"]["targetUuid"] == uuids["AI/transformer.md"]
    # dup → 同名两文件 → ambiguous（候选如实列出，绝不瞎猜）
    assert items["dup"]["status"] == "ambiguous"
    assert sorted(items["dup"]["candidates"]) == ["docs/dup.md", "other/dup.md"]
    # missing-note → broken；../outside → broken（越界）
    assert items["missing-note"]["status"] == "broken"
    assert items["missing-note"]["reason"] == "unresolved"
    assert items["../outside"]["reason"] == "path_escaped_vault"
    assert report["counts"]["ambiguous"] >= 1 and report["counts"]["broken"] >= 2

    # 范围过滤：只看一篇笔记；未知 uuid 诚实列出
    scoped = client.post(
        "/api/v1/obsidian/link-report",
        json={"noteUuids": [note_a, "no-such-uuid"]},
        headers=owner,
    ).json()
    assert scoped["unknownNoteUuids"] == ["no-such-uuid"]
    assert {i["noteUuid"] for i in scoped["items"]} == {note_a}


def test_new322_correction_pins_import_mapping(ab_env, tmp_path):  # noqa: F811
    client, owner = ab_env["client"], ab_env["owner"]
    uuids = _setup(client, owner, tmp_path)
    note_a = uuids["AI/注意力机制.md"]

    # 纠正目标不存在 → 400
    bad = client.put(
        "/api/v1/obsidian/link-report/corrections",
        json={"noteUuid": note_a, "raw": "dup", "targetUuid": "no-such"},
        headers=owner,
    )
    assert bad.status_code == 400
    # 源笔记不存在 → 404
    missing = client.put(
        "/api/v1/obsidian/link-report/corrections",
        json={"noteUuid": "no-such", "raw": "dup", "targetUuid": note_a},
        headers=owner,
    )
    assert missing.status_code == 404

    # 用户逐项纠正：[[dup]] 的导入映射钉到 docs/dup.md
    put = client.put(
        "/api/v1/obsidian/link-report/corrections",
        json={
            "noteUuid": note_a,
            "raw": "dup",
            "targetUuid": uuids["docs/dup.md"],
        },
        headers=owner,
    )
    assert put.status_code == 200, put.text

    report = client.post(
        "/api/v1/obsidian/link-report",
        json={"noteUuids": [note_a]},
        headers=owner,
    ).json()
    item = next(i for i in report["items"] if i["raw"] == "dup")
    assert item["status"] == "corrected"
    assert item["targetUuid"] == uuids["docs/dup.md"]

    corrections = client.get(
        "/api/v1/obsidian/link-report/corrections", headers=owner
    ).json()["corrections"]
    assert len(corrections) == 1
    assert corrections[0]["targetRelPath"] == "docs/dup.md"

    # 删除纠正 → 回到 ambiguous（如实还原）
    deleted = client.delete(
        "/api/v1/obsidian/link-report/corrections",
        params={"noteUuid": note_a, "raw": "dup"},
        headers=owner,
    )
    assert deleted.status_code == 200
    report = client.post(
        "/api/v1/obsidian/link-report",
        json={"noteUuids": [note_a]},
        headers=owner,
    ).json()
    item = next(i for i in report["items"] if i["raw"] == "dup")
    assert item["status"] == "ambiguous"


def test_new322_per_user_isolation_between_accounts(ab_env, tmp_path):  # noqa: F811
    client, owner, b = ab_env["client"], ab_env["owner"], ab_env["b"]
    uuids = _setup(client, owner, tmp_path)
    note_a = uuids["AI/注意力机制.md"]
    assert (
        client.put(
            "/api/v1/obsidian/link-report/corrections",
            json={"noteUuid": note_a, "raw": "dup", "targetUuid": note_a},
            headers=owner,
        ).status_code
        == 200
    )
    # 成员 B：报告 / 纠正列表 / 纠正写入全部 403
    assert (
        client.post("/api/v1/obsidian/link-report", json={}, headers=b).status_code
        == 403
    )
    assert (
        client.get(
            "/api/v1/obsidian/link-report/corrections", headers=b
        ).status_code
        == 403
    )
    put = client.put(
        "/api/v1/obsidian/link-report/corrections",
        json={"noteUuid": note_a, "raw": "transformer", "targetUuid": note_a},
        headers=b,
    )
    assert put.status_code == 403
    # owner 的纠正未被 B 的动作污染
    corrections = client.get(
        "/api/v1/obsidian/link-report/corrections", headers=owner
    ).json()["corrections"]
    assert len(corrections) == 1 and corrections[0]["raw"] == "dup"
