"""NEW-392 通知聚合规则 — 展示层聚合、原始事件完整保留、A/B 隔离。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from test_new391_notifications import _seed, _user_ids


def _seed_pair(env, user_id: str) -> tuple[dict, dict]:
    first = _seed(env, user_id, kind="task_failed", source="digest",
                  title="日报失败 1", ref="digest:1")
    second = _seed(env, user_id, kind="task_failed", source="digest",
                   title="日报失败 2", ref="digest:2")
    _seed(env, user_id, kind="share_event", source="space:alpha",
          title="共享事件", ref="space:alpha")
    return first, second


def test_new392_rule_crud_and_grouped_view(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    ids = _user_ids(ab_env)
    first, second = _seed_pair(ab_env, ids["a"])
    # 无规则 → 全部平铺
    flat = client.get("/api/v1/notifications/grouped", headers=a).json()
    assert flat["ruleCount"] == 0
    assert len(flat["flat"]) == 3 and flat["groups"] == []
    # 建规则：task_failed × digest
    created = client.post(
        "/api/v1/notifications/aggregation-rules",
        json={"kind": "task_failed", "source": "digest", "label": "日报"},
        headers=a,
    )
    assert created.status_code == 201, created.text
    rule = created.json()
    assert rule["enabled"] is True
    grouped = client.get("/api/v1/notifications/grouped", headers=a).json()
    assert grouped["ruleCount"] == 1
    assert len(grouped["groups"]) == 1
    group = grouped["groups"][0]
    assert group["kind"] == "task_failed" and group["source"] == "digest"
    assert group["total"] == 2 and group["unread"] == 2
    # 展开摘要 = 逐条原始事件（数据没有被合并/删除）
    assert sorted(item["id"] for item in group["items"]) == sorted(
        [first["id"], second["id"]]
    )
    assert [item["id"] for item in grouped["flat"]] and len(grouped["flat"]) == 1
    # 重复 (kind, source) → 409；坏类型 → 422
    dup = client.post(
        "/api/v1/notifications/aggregation-rules",
        json={"kind": "task_failed", "source": "digest"},
        headers=a,
    )
    assert dup.status_code == 409
    assert (
        client.post(
            "/api/v1/notifications/aggregation-rules",
            json={"kind": "nope", "source": "x"},
            headers=a,
        ).status_code
        == 422
    )
    # 停用 → 回到平铺；删除同理
    disabled = client.post(
        f"/api/v1/notifications/aggregation-rules/{rule['id']}/enabled",
        json={"enabled": False},
        headers=a,
    ).json()
    assert disabled["enabled"] is False
    flat_again = client.get("/api/v1/notifications/grouped", headers=a).json()
    assert flat_again["groups"] == [] and len(flat_again["flat"]) == 3
    removed = client.delete(
        f"/api/v1/notifications/aggregation-rules/{rule['id']}", headers=a
    )
    assert removed.status_code == 200
    assert client.get(
        "/api/v1/notifications/aggregation-rules", headers=a
    ).json()["rules"] == []


def test_new392_validation_and_missing(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    assert (
        client.post(
            "/api/v1/notifications/aggregation-rules/999999/enabled",
            json={"enabled": True},
            headers=a,
        ).status_code
        == 404
    )
    assert (
        client.delete(
            "/api/v1/notifications/aggregation-rules/999999", headers=a
        ).status_code
        == 404
    )
    blank_source = client.post(
        "/api/v1/notifications/aggregation-rules",
        json={"kind": "task_failed", "source": " "},
        headers=a,
    )
    assert blank_source.status_code in (400, 422)


def test_new392_ab_isolation(ab_env):  # noqa: F811
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    a_id, b_id = _user_ids(ab_env)["a"], _user_ids(ab_env)["b"]
    _seed_pair(ab_env, a_id)
    _seed(ab_env, b_id, kind="task_failed", source="other-source",
          title="B 的失败", ref="x:1")
    rule = client.post(
        "/api/v1/notifications/aggregation-rules",
        json={"kind": "task_failed", "source": "digest"},
        headers=a,
    ).json()
    # B 看不到 A 的规则，也不能改/删
    rules_b = client.get("/api/v1/notifications/aggregation-rules", headers=b).json()
    assert rules_b["rules"] == []
    assert (
        client.post(
            f"/api/v1/notifications/aggregation-rules/{rule['id']}/enabled",
            json={"enabled": False},
            headers=b,
        ).status_code
        == 404
    )
    # B 的聚合视图不被 A 的规则影响（来源不同）
    grouped_b = client.get("/api/v1/notifications/grouped", headers=b).json()
    assert grouped_b["ruleCount"] == 0 and len(grouped_b["flat"]) == 1
    # 同 (kind, source) 各自建规则互不冲突（唯一性按用户隔离）
    again = client.post(
        "/api/v1/notifications/aggregation-rules",
        json={"kind": "task_failed", "source": "digest"},
        headers=b,
    )
    assert again.status_code == 201
