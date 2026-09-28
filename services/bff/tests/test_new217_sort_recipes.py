"""NEW-217 集合排序配方 —— 多字段排序 + 固定例外，只作用于该集合。

验收：字段词表校验（422）；preview 零写入给出确定性新序（title 用本地
投影）；固定例外保持绝对原位；apply 真实写 position；其他集合不受影响；
explain 文案说明排序规则；404/422；A/B 隔离。
"""

import asyncio

from new21x_isolation import seed_entry

run = asyncio.run


def _mk_ws(client, name: str) -> str:
    created = client.post("/api/v1/workspaces", json={"name": name})
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _add(client, ws: str, ref: str) -> None:
    added = client.post(f"/api/v1/workspaces/{ws}/items", json={"itemRef": ref})
    assert added.status_code == 201, added.text


def _members(client, ws: str) -> list[tuple[str, int]]:
    items = client.get(f"/api/v1/workspaces/{ws}/items").json()["items"]
    return [(i["itemRef"], i["position"]) for i in items]


def test_new217_recipe_preview_apply_and_exceptions(client):
    ref_z = seed_entry(client, "z1", title="香蕉研究报告")
    ref_a = seed_entry(client, "a1", title="苹果周报")
    ref_m = seed_entry(client, "m1", title="芒果随笔")
    ws = _mk_ws(client, "排序集合")
    other = _mk_ws(client, "无关集合")
    for ref in (ref_z, ref_a, ref_m):
        _add(client, ws, ref)
    _add(client, other, ref_z)

    # 校验：字段词表 / 未知集合
    bad_key = client.post(
        f"/api/v1/workspaces/{ws}/sort-recipes",
        json={"name": "坏配方", "fields": [{"key": "magic", "dir": "asc"}]},
    )
    assert bad_key.status_code == 422
    assert bad_key.json()["error"]["type"] == "invalid_sort_recipe"
    bad_ws = client.post(
        "/api/v1/workspaces/no-such-ws/sort-recipes",
        json={"name": "配方", "fields": [{"key": "title", "dir": "asc"}]},
    )
    assert bad_ws.status_code == 422

    created = client.post(
        f"/api/v1/workspaces/{ws}/sort-recipes",
        json={
            "name": "标题升序",
            "fields": [{"key": "title", "dir": "asc"}],
            "exceptions": [ref_a],  # 苹果周报固定原位（position 2）
        },
    )
    assert created.status_code == 201, created.text
    recipe = created.json()
    assert recipe["explain"] and "标题" in recipe["explain"] and "1 条固定例外" in recipe["explain"]

    # preview 零写入：香蕉(3)→升序后……固定例外 ref_a 保持 position 2
    before = dict(_members(client, ws))
    preview = client.post(
        f"/api/v1/workspaces/{ws}/sort-recipes/{recipe['id']}/preview"
    )
    assert preview.status_code == 200, preview.text
    ordering = preview.json()["ordering"]
    pos = {o["ref"]: o["position"] for o in ordering}
    assert pos[ref_a] == 2 and ordering[1]["fixed"] is True  # 固定例外原位
    assert pos[ref_m] == 1 and pos[ref_z] == 3  # 芒果 < 香蕉（拼音无关，Unicode 序：芒 U+8292 < 香 U+9999）
    assert dict(_members(client, ws)) == before  # 预览零写入

    # apply 真实写库
    applied = client.post(f"/api/v1/workspaces/{ws}/sort-recipes/{recipe['id']}/apply")
    assert applied.status_code == 200, applied.text
    after = dict(_members(client, ws))
    assert after[ref_a] == 2 and after[ref_m] == 1 and after[ref_z] == 3
    # 其他集合不受影响
    assert dict(_members(client, other))[ref_z] == 1

    # 404 + 删除
    assert (
        client.post(
            f"/api/v1/workspaces/{ws}/sort-recipes/no-such/preview"
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/workspaces/{ws}/sort-recipes/{recipe['id']}"
        ).status_code
        == 204
    )
    assert (
        client.delete(
            f"/api/v1/workspaces/{ws}/sort-recipes/{recipe['id']}"
        ).status_code
        == 404
    )


def test_new217_per_user_isolation(monkeypatch, tmp_path):
    """per-user 库：A 的配方对 B 不可见；B 也不该 apply 到 A 的集合。"""
    from new21x_isolation import build_two_user_client, isolated_auth_env, make_bookmark

    isolated_auth_env(monkeypatch, tmp_path)
    for client, owner, member in build_two_user_client():
        ref = make_bookmark(client, member, "乙的成员")
        ws = client.post(
            "/api/v1/workspaces", json={"name": "乙的集合"}, headers=member
        ).json()["id"]
        client.post(
            f"/api/v1/workspaces/{ws}/items", json={"itemRef": ref}, headers=member
        )
        recipe = client.post(
            f"/api/v1/workspaces/{ws}/sort-recipes",
            json={"name": "乙的配方", "fields": [{"key": "added_at", "dir": "desc"}]},
            headers=member,
        )
        assert recipe.status_code == 201, recipe.text

        # A 看不到配方，也动不了 B 的集合
        assert (
            client.get(
                f"/api/v1/workspaces/{ws}/sort-recipes", headers=owner
            ).json()["items"]
            == []
        )
        assert (
            client.post(
                f"/api/v1/workspaces/{ws}/sort-recipes/{recipe.json()['id']}/apply",
                headers=owner,
            ).status_code
            == 404
        )
        # B 自己可用
        assert (
            client.post(
                f"/api/v1/workspaces/{ws}/sort-recipes/{recipe.json()['id']}/apply",
                headers=member,
            ).status_code
            == 200
        )
