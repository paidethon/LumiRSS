"""NEW-223 队列工作量预览（服务端）。

- 阅读速度设置（缺省 400 明示 customized=false；人工校正边界
  50..2000）；
- 估算诚实性：已知按 ceil(len/速度) 求和；无投影文本 → minutes=null
  + unknownCount（绝不瞎猜）；响应恒带 basis +「估算是数量级参考」；
- 压缩范围是建议清单（用户挑），响应 note 明示服务端不裁队列；
- A/B 每用户隔离（速度设置互不可见）。
"""


from new2xx_ab import ab_env, seed_entry  # noqa: F401,F811


def test_speed_default_and_custom(ab_env):  # noqa: F811
    client = ab_env["client"]
    default = client.get("/api/v1/queue/workload/speed", headers=ab_env["a"])
    assert default.status_code == 200
    body = default.json()
    assert body["charsPerMinute"] == 400
    assert body["customized"] is False
    assert "校正" in (body["note"] or "")

    updated = client.put(
        "/api/v1/queue/workload/speed",
        json={"charsPerMinute": 250},
        headers=ab_env["a"],
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["charsPerMinute"] == 250
    assert updated.json()["customized"] is True

    out_of_bounds = client.put(
        "/api/v1/queue/workload/speed",
        json={"charsPerMinute": 49},
        headers=ab_env["a"],
    )
    assert out_of_bounds.status_code == 422
    fast = client.put(
        "/api/v1/queue/workload/speed",
        json={"charsPerMinute": 2001},
        headers=ab_env["a"],
    )
    assert fast.status_code == 422


def test_estimate_known_unknown_and_basis(ab_env):  # noqa: F811
    client = ab_env["client"]
    client.put(
        "/api/v1/queue/workload/speed",
        json={"charsPerMinute": 400},
        headers=ab_env["a"],
    )
    ref1 = seed_entry(ab_env, "a", "w1", title="短文", content_text="字" * 400)
    ref2 = seed_entry(ab_env, "a", "w2", title="长文", content_text="字" * 1000)
    ref_missing = "rss:ghost-ref-no-projection"  # 无投影 → 诚实未知

    est = client.post(
        "/api/v1/queue/workload/estimate",
        json={"refs": [ref1, ref2, ref_missing]},
        headers=ab_env["a"],
    )
    assert est.status_code == 200, est.text
    body = est.json()
    assert body["charsPerMinute"] == 400
    minutes = {item["itemRef"]: item["minutes"] for item in body["items"]}
    assert minutes[ref1] == 1  # ceil(400/400)
    assert minutes[ref2] == 3  # ceil(1000/400)
    assert minutes[ref_missing] is None
    assert body["totalKnownMinutes"] == 4
    assert body["unknownCount"] == 1
    assert "ceil" in body["basis"]
    assert "不是精确" in body["note"]

    empty = client.post(
        "/api/v1/queue/workload/estimate", json={"refs": []}, headers=ab_env["a"]
    )
    # pydantic min_length=1 先拦（invalid_request）；越界速度走 invalid_workload。
    assert empty.status_code == 422


def test_compressions_are_suggestions_not_cuts(ab_env):  # noqa: F811
    client = ab_env["client"]
    refs = [
        seed_entry(ab_env, "a", f"c{i}", title=f"c{i}", content_text="字" * (200 * i + 200))
        for i in range(6)
    ]
    comp = client.post(
        "/api/v1/queue/workload/compressions",
        json={"refs": refs},
        headers=ab_env["a"],
    )
    assert comp.status_code == 200, comp.text
    body = comp.json()
    keys = [option["key"] for option in body["options"]]
    assert keys[0] == "keep_all"
    assert len(keys) >= 3  # 前半 / 剔除最长 / 只留短文
    keep_all = body["options"][0]
    assert keep_all["estimatedMinutes"] >= body["options"][1]["estimatedMinutes"]
    for option in body["options"][1:]:
        assert len(option["refs"]) < len(refs)
    assert "不会替你裁队列" in body["note"]


def test_ab_speed_isolation(ab_env):  # noqa: F811
    client = ab_env["client"]
    client.put(
        "/api/v1/queue/workload/speed",
        json={"charsPerMinute": 250},
        headers=ab_env["a"],
    )
    b_view = client.get("/api/v1/queue/workload/speed", headers=ab_env["b"])
    assert b_view.status_code == 200
    assert b_view.json()["charsPerMinute"] == 400
    assert b_view.json()["customized"] is False
