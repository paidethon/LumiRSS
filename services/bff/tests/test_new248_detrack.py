"""NEW-248 来源链接去追踪预览 — 预览分组 / 用户保留参数 / 隔离。

- 预览：已知追踪参数（utm_*、fbclid 等）→ removed；token/签名/清单外
  未知参数 → keptRequired（保守保留，登录与内容选择参数天然存活）；
  用户标记 → keptUser；非 http(s) → supported=false；
- 保留参数：PUT 标记 → 预览改入 keptUser；DELETE 撤销 → 恢复可移除；
- 校验：参数名含 = & 422；空 url 422；
- 隔离：A 的保留参数不影响 B 的预览（真实 RoutingDatabase per-user 库）。
"""

from new231_helpers import ab_session


def test_new248_preview_groups_and_kept_params(client):
    """追踪参数进 removed；签名/未知参数保守保留；用户可标记保留与撤销。"""
    preview = client.post(
        "/api/v1/links/detrack-preview",
        json={"url": "https://s.example/article?utm_source=rss&fbclid=abc&id=42&token=keepme&_signature=sig"},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["supported"] is True
    assert body["removed"] == ["utm_source", "fbclid"]
    assert body["keptRequired"] == ["id", "token", "_signature"]  # 内容选择 + 保护类
    assert "id=42" in body["cleanedUrl"] and "token=keepme" in body["cleanedUrl"]
    assert "utm_source" not in body["cleanedUrl"]

    # 用户标记 utm_medium 必须保留（例如某个站点用它做内容选择）→ 预览改入 keptUser
    put = client.put(
        "/api/v1/links/detrack-kept-params/utm_medium", json={"reason": "该站靠它区分栏目"}
    )
    assert put.status_code == 200, put.text
    preview2 = client.post(
        "/api/v1/links/detrack-preview",
        json={"url": "https://s.example/a?utm_medium=col&id=1"},
    )
    body2 = preview2.json()
    assert body2["keptUser"] == ["utm_medium"]
    assert "utm_medium" not in body2["removed"]
    assert "utm_medium=col" in body2["cleanedUrl"]

    listed = client.get("/api/v1/links/detrack-kept-params")
    assert [i["param"] for i in listed.json()["items"]] == ["utm_medium"]

    # 撤销保留 → 恢复可移除
    removed = client.delete("/api/v1/links/detrack-kept-params/utm_medium")
    assert removed.status_code == 204
    preview3 = client.post(
        "/api/v1/links/detrack-preview",
        json={"url": "https://s.example/a?utm_medium=col"},
    )
    assert preview3.json()["removed"] == ["utm_medium"]

    # 非 http(s) → 诚实 unsupported，不做任何移除
    bad = client.post(
        "/api/v1/links/detrack-preview", json={"url": "javascript:alert(1)?utm_source=x"}
    )
    assert bad.status_code == 200
    assert bad.json()["supported"] is False


def test_new248_validation(client):
    empty = client.post("/api/v1/links/detrack-preview", json={"url": ""})
    assert empty.status_code == 422

    bad_param = client.put("/api/v1/links/detrack-kept-params/a=b", json={})
    assert bad_param.status_code == 422
    assert bad_param.json()["error"]["type"] == "detrack_invalid"

    spaces = client.put("/api/v1/links/detrack-kept-params/%20x", json={})
    assert spaces.status_code == 422


def test_new248_isolation_between_users(monkeypatch, tmp_path):
    """A 标记的保留参数不影响 B 的预览（真实 RoutingDatabase per-user 库）。"""
    with ab_session(monkeypatch, tmp_path) as session:
        member = session.activate_member("n24x-b")
        put = session.client.put(
            "/api/v1/links/detrack-kept-params/utm_campaign",
            json={"reason": "A 的理由"},
            headers=session.owner,
        )
        assert put.status_code == 200, put.text

        b_preview = session.client.post(
            "/api/v1/links/detrack-preview",
            json={"url": "https://s.example/a?utm_campaign=x"},
            headers=member,
        )
        assert b_preview.status_code == 200
        assert b_preview.json()["keptUser"] == []
        assert b_preview.json()["removed"] == ["utm_campaign"]

        a_preview = session.client.post(
            "/api/v1/links/detrack-preview",
            json={"url": "https://s.example/a?utm_campaign=x"},
            headers=session.owner,
        )
        assert a_preview.json()["keptUser"] == ["utm_campaign"]
