"""NEW-315 书签链接批量替换 — 预览逐项变化、执行、冲突诚实、撤销本批、A/B 隔离。"""

import pytest

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册

APPLY = "/api/v1/library/bookmarks/link-replace/apply"
PREVIEW = "/api/v1/library/bookmarks/link-replace/preview"


def _mk_bookmark(client, headers, title: str, url: str) -> str:
    made = client.post(
        "/api/v1/library/bookmarks", json={"title": title, "url": url}, headers=headers
    )
    assert made.status_code == 201, made.text
    return made.json()["ref"]


def _urls(client, headers) -> dict[str, str]:
    return {
        b["ref"]: str(b["url"])
        for b in client.get("/api/v1/library/bookmarks", headers=headers).json()["items"]
        if b.get("url")
    }


def test_new315_preview_then_apply_domain_map_and_undo_batch(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    old = _mk_bookmark(client, a, "旧站文章", "https://old.example.com/posts/1?utm=x#top")
    other = _mk_bookmark(client, a, "别的域", "https://keep.example.org/a")
    subdomain = _mk_bookmark(client, a, "子域不算", "https://cdn.old.example.com/x")

    # 预览零写入：只有精确 host 匹配的旧站文章被列出；子域不算
    preview = client.post(
        PREVIEW, json={"fromDomain": "old.example.com", "toDomain": "new.example.com"}, headers=a
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert [c["ref"] for c in body["changes"]] == [old]
    assert body["changes"][0]["before"] == "https://old.example.com/posts/1?utm=x#top"
    assert body["changes"][0]["after"] == "https://new.example.com/posts/1?utm=x#top"
    urls = _urls(client, a)
    assert urls[old].endswith("posts/1?utm=x#top") and "old.example.com" in urls[old]

    # 执行：路径/查询/fragment 原样保留
    applied = client.post(
        APPLY, json={"fromDomain": "old.example.com", "toDomain": "new.example.com"}, headers=a
    )
    assert applied.status_code == 200, applied.text
    result = applied.json()
    assert result["changed"] == 1 and result["conflicts"] == []
    urls = _urls(client, a)
    assert urls[old] == "https://new.example.com/posts/1?utm=x#top"
    assert urls[other] == "https://keep.example.org/a"
    assert urls[subdomain] == "https://cdn.old.example.com/x"

    # 撤销本批 → 精确回到执行前
    undo = client.post(
        f"/api/v1/library/bookmarks/link-replace/batches/{result['id']}/undo", headers=a
    )
    assert undo.status_code == 200, undo.text
    assert undo.json()["restored"] == 1
    assert _urls(client, a)[old] == "https://old.example.com/posts/1?utm=x#top"

    # 同批不能二次撤销（409）
    again = client.post(
        f"/api/v1/library/bookmarks/link-replace/batches/{result['id']}/undo", headers=a
    )
    assert again.status_code == 409

    batches = client.get(
        "/api/v1/library/bookmarks/link-replace/batches", headers=a
    ).json()["batches"]
    assert len(batches) == 1 and batches[0]["undone"] is True


def test_new315_conflicts_reported_honestly_not_silently_dropped(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    target = _mk_bookmark(client, a, "新站已存在", "https://new.example.com/dup")
    source = _mk_bookmark(client, a, "旧站待迁移", "https://old.example.com/dup")

    applied = client.post(
        APPLY, json={"fromDomain": "old.example.com", "toDomain": "new.example.com"}, headers=a
    )
    assert applied.status_code == 200
    result = applied.json()
    assert result["changed"] == 0
    assert len(result["conflicts"]) == 1
    assert result["conflicts"][0]["ref"] == source
    # 源书签保持原 URL（绝不静默覆盖/丢弃）
    assert _urls(client, a)[source] == "https://old.example.com/dup"
    assert _urls(client, a)[target] == "https://new.example.com/dup"


def test_new315_empty_domains_rejected_422_by_request_shape(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    assert (
        client.post(
            PREVIEW, json={"fromDomain": "old.example.com", "toDomain": ""}, headers=a
        ).status_code
        == 422
    )
    assert (
        client.post(
            PREVIEW, json={"fromDomain": "", "toDomain": "new.example.com"}, headers=a
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "body",
    [
        {"fromDomain": "old.example.com/path", "toDomain": "new.example.com"},
        {"fromDomain": "*.old.example.com", "toDomain": "new.example.com"},
        {"fromDomain": "old.example.com", "toDomain": "new.example.com/slash"},
    ],
)
def test_new315_invalid_mappings_rejected_400(ab_env, body):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    bad = client.post(PREVIEW, json=body, headers=a)
    assert bad.status_code == 400
    assert bad.json()["error"]["type"] == "invalid_domain_mapping"


def test_new315_per_user_isolation_between_accounts(ab_env):  # noqa: F811
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    a_book = _mk_bookmark(client, a, "A 的旧站", "https://old.example.com/only-a")

    # A 的预览/执行只看 A 的书签；B 无书签
    preview_b = client.post(
        PREVIEW, json={"fromDomain": "old.example.com", "toDomain": "new.example.com"}, headers=b
    )
    assert preview_b.json()["changes"] == []

    applied = client.post(
        APPLY, json={"fromDomain": "old.example.com", "toDomain": "new.example.com"}, headers=a
    )
    batch_id = applied.json()["id"]

    # B 不能撤销 A 的批次（404）；A 的台账对 B 不可见
    assert (
        client.post(
            f"/api/v1/library/bookmarks/link-replace/batches/{batch_id}/undo", headers=b
        ).status_code
        == 404
    )
    assert (
        client.get("/api/v1/library/bookmarks/link-replace/batches", headers=b).json()[
            "batches"
        ]
        == []
    )
    assert _urls(client, a)[a_book].startswith("https://new.example.com/only-a")
