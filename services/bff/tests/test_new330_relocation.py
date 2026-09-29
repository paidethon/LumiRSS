"""NEW-330 资料路径重定位向导 — 按 content-hash 匹配原条目，不重复导入。"""

import shutil

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from test_new325_root_profiles import _create_root

NOTE_A = "---\ntitle: A\n---\n内容甲。\n"
NOTE_B = "---\ntitle: B\n---\n内容乙。\n"


def _scan(client, headers, root_id):
    return client.post(f"/api/v1/obsidian/roots/{root_id}/scan", headers=headers)


def test_new330_relocation_matches_by_checksum_without_reimport(ab_env, tmp_path):  # noqa: F811
    client, owner = ab_env["client"], ab_env["owner"]
    old_root = _create_root(
        client, owner, tmp_path, name="移动前的库",
        files={"a.md": NOTE_A, "b.md": NOTE_B}, root_name="root-old",
    )
    report = _scan(client, owner, old_root["id"]).json()
    assert report["added"] == 2
    from new321_vault import note_uuids as _not_used  # noqa: F401

    notes_before = client.get(
        f"/api/v1/obsidian/roots/{old_root['id']}/notes", headers=owner
    ).json()["notes"]
    ids_before = {n["relPath"]: n["id"] for n in notes_before}
    hashes_before = {n["relPath"]: n["contentHash"] for n in notes_before}

    # 源目录重组：内容移进 notes/ 子目录 + 新增文件（路径全变、内容不变）
    new_root = tmp_path / "root-new"
    (new_root / "notes").mkdir(parents=True)
    shutil.move(str(tmp_path / "root-old" / "a.md"), str(new_root / "notes" / "a.md"))
    shutil.move(str(tmp_path / "root-old" / "b.md"), str(new_root / "notes" / "b.md"))
    (new_root / "extra.md").write_text("---\ntitle: 新增\n---\n新内容\n", encoding="utf-8")

    preview = client.post(
        f"/api/v1/obsidian/roots/{old_root['id']}/relocate/preview",
        json={"newPath": str(new_root)},
        headers=owner,
    )
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert plan["status"] == "previewed"
    assert plan["counts"]["relocated"] == 2  # 校验和唯一匹配
    assert plan["counts"]["fresh"] == 1
    assert plan["counts"]["vanished"] == 0
    relocated = {m["from"]: m["to"] for m in plan["relocated"]}
    assert relocated == {"a.md": "notes/a.md", "b.md": "notes/b.md"}

    # 预览零写入
    notes_mid = client.get(
        f"/api/v1/obsidian/roots/{old_root['id']}/notes", headers=owner
    ).json()["notes"]
    assert {n["relPath"] for n in notes_mid} == {"a.md", "b.md"}

    # 应用：路径接续（行 id 不变 = 不重复导入），档案根切到新路径
    applied = client.post(
        f"/api/v1/obsidian/roots/{old_root['id']}/relocate/{plan['id']}/apply",
        headers=owner,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["relocatedApplied"] == 2
    profile = client.get(f"/api/v1/obsidian/roots/{old_root['id']}", headers=owner).json()
    assert profile["rootPath"] == str(new_root)

    notes_after = client.get(
        f"/api/v1/obsidian/roots/{old_root['id']}/notes", headers=owner
    ).json()["notes"]
    assert {n["relPath"] for n in notes_after} == {"notes/a.md", "notes/b.md"}
    ids_after = {n["relPath"]: n["id"] for n in notes_after}
    assert ids_after["notes/a.md"] == ids_before["a.md"]  # 行身份保持
    assert ids_after["notes/b.md"] == ids_before["b.md"]
    hashes_after = {n["relPath"]: n["contentHash"] for n in notes_after}
    assert hashes_after["notes/a.md"] == hashes_before["a.md"]

    # 下一次扫描：extra.md 如实新增，且无重复导入
    rescan = _scan(client, owner, old_root["id"])
    assert rescan.status_code == 200
    assert rescan.json()["added"] == 1  # 只有 extra.md
    final_notes = client.get(
        f"/api/v1/obsidian/roots/{old_root['id']}/notes", headers=owner
    ).json()["notes"]
    assert len(final_notes) == 3

    # 已应用的向导记录不可重复应用；历史可查
    assert (
        client.post(
            f"/api/v1/obsidian/roots/{old_root['id']}/relocate/{plan['id']}/apply",
            headers=owner,
        ).status_code
        == 409
    )
    history = client.get(
        f"/api/v1/obsidian/roots/{old_root['id']}/relocate", headers=owner
    ).json()["relocations"]
    assert len(history) == 1 and history[0]["status"] == "applied"


def test_new330_ambiguous_hashes_never_guessed_and_vanished_listed(ab_env, tmp_path):  # noqa: F811
    client, owner = ab_env["client"], ab_env["owner"]
    old_root = _create_root(
        client, owner, tmp_path, name="歧义库",
        files={"a.md": NOTE_A, "b.md": NOTE_B}, root_name="root-amb-old",
    )
    assert _scan(client, owner, old_root["id"]).json()["added"] == 2

    new_root = tmp_path / "root-amb-new"
    new_root.mkdir()
    # 同内容出现两份 → 哈希多候选，绝不瞎猜
    (new_root / "copy1.md").write_text(NOTE_A, encoding="utf-8")
    (new_root / "copy2.md").write_text(NOTE_A, encoding="utf-8")
    (new_root / "other.md").write_text("---\ntitle: 其他\n---\n其他内容\n", encoding="utf-8")
    # b.md 的内容在新根不存在 → vanished
    preview = client.post(
        f"/api/v1/obsidian/roots/{old_root['id']}/relocate/preview",
        json={"newPath": str(new_root)},
        headers=owner,
    ).json()
    assert preview["counts"]["ambiguous"] == 2
    assert sorted(preview["ambiguous"]) == ["copy1.md", "copy2.md"]
    assert preview["counts"]["vanished"] == 1
    assert preview["vanished"] == ["b.md"]
    # 应用未受歧义影响：0 条被改
    applied = client.post(
        f"/api/v1/obsidian/roots/{old_root['id']}/relocate/{preview['id']}/apply",
        headers=owner,
    )
    assert applied.status_code == 200
    assert applied.json()["relocatedApplied"] == 0

    # 校验：新根不可达 → 503；空路径 → 400；未知根 → 404
    assert (
        client.post(
            f"/api/v1/obsidian/roots/{old_root['id']}/relocate/preview",
            json={"newPath": str(tmp_path / "no-such-330")},
            headers=owner,
        ).status_code
        == 503
    )
    assert (
        client.post(
            f"/api/v1/obsidian/roots/{old_root['id']}/relocate/preview",
            json={"newPath": ""},
            headers=owner,
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/obsidian/roots/no-such/relocate/preview",
            json={"newPath": str(new_root)},
            headers=owner,
        ).status_code
        == 404
    )


def test_new330_per_user_isolation_between_accounts(ab_env, tmp_path):  # noqa: F811
    client, owner, b = ab_env["client"], ab_env["owner"], ab_env["b"]
    old_root = _create_root(
        client, owner, tmp_path, name="A 的库",
        files={"a.md": NOTE_A}, root_name="root-iso-330",
    )
    assert _scan(client, owner, old_root["id"]).json()["added"] == 1
    preview = client.post(
        f"/api/v1/obsidian/roots/{old_root['id']}/relocate/preview",
        json={"newPath": str(tmp_path / "root-iso-330")},
        headers=owner,
    ).json()
    for method, path, kwargs in (
        ("post", f"/api/v1/obsidian/roots/{old_root['id']}/relocate/preview",
         {"json": {"newPath": str(tmp_path / "root-iso-330")}}),
        ("post", f"/api/v1/obsidian/roots/{old_root['id']}/relocate/{preview['id']}/apply", {}),
        ("get", f"/api/v1/obsidian/roots/{old_root['id']}/relocate", {}),
    ):
        response = getattr(client, method)(path, headers=b, **kwargs)
        assert response.status_code == 403, (method, path, response.text)
    # A 的档案未被 B 触碰（仍指向原根、preview 仍 pending 无人应用）
    profile = client.get(f"/api/v1/obsidian/roots/{old_root['id']}", headers=owner).json()
    assert profile["rootPath"] == str(tmp_path / "root-iso-330")
    notes = client.get(
        f"/api/v1/obsidian/roots/{old_root['id']}/notes", headers=owner
    ).json()["notes"]
    assert [n["relPath"] for n in notes] == ["a.md"]
