"""NEW-345 共享链接使用次数上限 — 耗尽 410/被拒访问留痕不计数/手动
续额保留历史/上限设置的诚实语义 + A/B 隔离。（零真实网络）"""

import asyncio

from new2xx_ab import ab_env, seed_entry  # noqa: F401 — pytest 夹具注册

LINKS_PATH = "/api/v1/privacy/share-links"


def _make_link(env, *, max_uses=None):
    from lumirss.entryref import encode_entry_ref

    seed_entry(env, "a", "n345-item-1", title="限额文章", content_text="正文" * 50)
    ref = encode_entry_ref("n345-item-1")
    body = {"title": "限额链接", "scope": "titles", "entryRefs": [ref]}
    if max_uses is not None:
        body["maxUses"] = max_uses
    created = env["client"].post(LINKS_PATH, json=body, headers=env["a"])
    assert created.status_code == 201, created.text
    return created.json()


def test_new345_exhaust_then_410_rejected_access_recorded(ab_env):  # noqa: F811
    client = ab_env["client"]
    link = _make_link(ab_env, max_uses=2)
    token = link["token"]
    assert client.get(f"/shares/{token}").status_code == 200
    assert client.get(f"/shares/{token}").status_code == 200

    exhausted = client.get(f"/shares/{token}")
    assert exhausted.status_code == 410
    assert exhausted.json()["error"]["type"] == "share_link_exhausted"

    accesses = client.get(
        f"{LINKS_PATH}/{link['id']}/accesses", headers=ab_env["a"]
    ).json()["items"]
    results = [row["result"] for row in accesses]
    assert results.count("served") == 2
    assert results.count("limit_reached") == 1

    state = client.get(LINKS_PATH, headers=ab_env["a"]).json()["items"][0]
    assert state["useCount"] == 2  # 被拒访问不计数
    assert state["exhaustedAt"] is not None


def test_new345_topup_restores_and_keeps_history(ab_env):  # noqa: F811
    client = ab_env["client"]
    link = _make_link(ab_env, max_uses=1)
    token = link["token"]
    assert client.get(f"/shares/{token}").status_code == 200
    assert client.get(f"/shares/{token}").status_code == 410

    topup = client.post(
        f"{LINKS_PATH}/{link['id']}/topup",
        json={"addUses": 3},
        headers=ab_env["a"],
    )
    assert topup.status_code == 200, topup.text
    body = topup.json()
    assert body["maxUses"] == 4  # 原上限 1 + 续 3
    assert body["useCount"] == 1
    assert "保留" in body["note"]
    assert client.get(f"/shares/{token}").status_code == 200

    accesses = client.get(
        f"{LINKS_PATH}/{link['id']}/accesses", headers=ab_env["a"]
    ).json()["items"]
    assert len(accesses) == 3  # 历史访问（含被拒）不因续额清除

    invalid = client.post(
        f"{LINKS_PATH}/{link['id']}/topup",
        json={"addUses": 0},
        headers=ab_env["a"],
    )
    assert invalid.status_code == 422


def test_new345_set_limit_and_ab_isolation(ab_env):  # noqa: F811
    client = ab_env["client"]
    link = _make_link(ab_env)  # 不限
    # B 看不到也改不了 A 的链接。
    b_patch = ab_env["client"].post(
        f"{LINKS_PATH}/{link['id']}/limit",
        json={"maxUses": 1},
        headers=ab_env["b"],
    )
    assert b_patch.status_code == 404
    b_list = ab_env["client"].get(LINKS_PATH, headers=ab_env["b"]).json()["items"]
    assert all(item["id"] != link["id"] for item in b_list)

    patched = client.post(
        f"{LINKS_PATH}/{link['id']}/limit", json={"maxUses": 5}, headers=ab_env["a"]
    )
    assert patched.status_code == 200
    assert patched.json()["maxUses"] == 5

    unlimited = client.post(
        f"{LINKS_PATH}/{link['id']}/limit", json={"maxUses": None}, headers=ab_env["a"]
    )
    assert unlimited.status_code == 200
    assert unlimited.json()["maxUses"] is None

    bad = client.post(
        f"{LINKS_PATH}/{link['id']}/limit", json={"maxUses": 0}, headers=ab_env["a"]
    )
    assert bad.status_code == 422


def test_new345_evaluate_access_pure():
    from lumirss.new345_share_link_limits import evaluate_access

    assert evaluate_access({"revokedAt": None, "maxUses": None, "useCount": 99}) == "served"
    assert evaluate_access({"revokedAt": "t", "maxUses": 1, "useCount": 0}) == "not_found"
    assert evaluate_access({"revokedAt": None, "maxUses": 2, "useCount": 2}) == "limit_reached"
    assert evaluate_access({"revokedAt": None, "maxUses": 2, "useCount": 1}) == "served"


def test_new345_record_access_module_level():
    """模块层：served 累加 + 首次耗尽写 exhausted_at（真实库）。"""
    from lumirss.entryref import encode_entry_ref
    from lumirss.new344_share_links import ShareLinkStore
    from lumirss.new345_share_link_limits import record_access
    from lumirss.storage import Database

    async def run():
        db = Database("/tmp/n345-direct/lumi.sqlite")
        store = ShareLinkStore(db)
        created = await store.create(
            title="模块层",
            scope="titles",
            entry_refs=[encode_entry_ref("n345-direct-1")],
            excerpt_chars=0,
            max_uses=2,
        )
        link_id = created["id"]
        await record_access(db, link_id, "served", now="2026-09-01T00:00:00+00:00")
        await record_access(db, link_id, "served", now="2026-09-01T00:01:00+00:00")
        row = await store.get(link_id)
        return row

    state = asyncio.run(run())
    assert state["useCount"] == 2 and state["exhaustedAt"] is not None
