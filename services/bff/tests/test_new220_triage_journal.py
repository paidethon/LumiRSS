"""NEW-220 个人收件箱处理记录 —— 整理轨迹台账。

验收：写入从哪里移到哪里 + 原因（校验：同位置拒绝、引用形状、原因
长度）；按日期分组追踪 + 位置过滤；删除 + 404；A/B 隔离。
"""

REF_1 = "library:11111111-1111-4111-8111-111111111111"
REF_2 = "library:22222222-2222-4222-8222-222222222222"


def test_new220_journal_create_track_and_delete(client):
    created = client.post(
        "/api/v1/triage-journal",
        json={
            "fromLocation": "收件箱",
            "toLocation": "工作区:行业跟踪",
            "refs": [REF_1, REF_2, REF_1],  # 重复引用折叠
            "reason": "周报类内容集中管理",
        },
    )
    assert created.status_code == 201, created.text
    entry = created.json()
    assert entry["refs"] == [REF_1, REF_2]
    assert entry["reason"] == "周报类内容集中管理"

    second = client.post(
        "/api/v1/triage-journal",
        json={
            "fromLocation": "稍后读",
            "toLocation": "归档",
            "refs": [REF_2],
            "reason": "读完归档",
        },
    )
    assert second.status_code == 201

    # 校验：同位置 / 坏引用 / 原因超长 / 坏日期
    same = client.post(
        "/api/v1/triage-journal",
        json={"fromLocation": "收件箱", "toLocation": "收件箱", "refs": [REF_1]},
    )
    assert same.status_code == 422
    assert same.json()["error"]["type"] == "invalid_triage_journal"
    bad_ref = client.post(
        "/api/v1/triage-journal",
        json={"fromLocation": "收件箱", "toLocation": "归档", "refs": ["not-a-ref"]},
    )
    assert bad_ref.status_code == 422
    long_reason = client.post(
        "/api/v1/triage-journal",
        json={
            "fromLocation": "收件箱",
            "toLocation": "归档",
            "refs": [REF_1],
            "reason": "长" * 501,
        },
    )
    assert long_reason.status_code == 422
    bad_date = client.get("/api/v1/triage-journal", params={"date": "2026/09/28"})
    assert bad_date.status_code == 422

    # 追踪：按日分组（倒序）、位置过滤
    trail = client.get("/api/v1/triage-journal").json()
    assert trail["count"] == 2
    assert [d["date"] for d in trail["days"]] == sorted(
        (d["date"] for d in trail["days"]), reverse=True
    )
    assert sum(len(d["entries"]) for d in trail["days"]) == 2
    filtered = client.get(
        "/api/v1/triage-journal", params={"location": "工作区"}
    ).json()
    assert filtered["count"] == 1
    assert filtered["days"][0]["entries"][0]["toLocation"] == "工作区:行业跟踪"

    # 删除 + 404
    assert client.delete(f"/api/v1/triage-journal/{entry['id']}").status_code == 204
    assert client.delete(f"/api/v1/triage-journal/{entry['id']}").status_code == 404
    assert client.get("/api/v1/triage-journal").json()["count"] == 1


def test_new220_per_user_isolation(monkeypatch, tmp_path):
    """per-user 库：B 的整理记录对 A 不可见、不可删。"""
    from new21x_isolation import build_two_user_client, isolated_auth_env

    isolated_auth_env(monkeypatch, tmp_path)
    for client, owner, member in build_two_user_client():
        created = client.post(
            "/api/v1/triage-journal",
            json={
                "fromLocation": "收件箱",
                "toLocation": "乙的归档",
                "refs": [REF_1],
                "reason": "乙的原因",
            },
            headers=member,
        )
        assert created.status_code == 201, created.text
        entry_id = created.json()["id"]

        # A 看不到 B 的轨迹，也删不到
        assert client.get("/api/v1/triage-journal", headers=owner).json()["count"] == 0
        assert (
            client.delete(f"/api/v1/triage-journal/{entry_id}", headers=owner).status_code
            == 404
        )
        # B 自己可见、可删
        assert client.get("/api/v1/triage-journal", headers=member).json()["count"] == 1
        assert (
            client.delete(f"/api/v1/triage-journal/{entry_id}", headers=member).status_code
            == 204
        )
