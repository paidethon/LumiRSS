"""NEW-246 资料来源链 — 手工引用边 + 链条追踪（不推断）+ 隔离。

- a→b→c 链：从 a 出发沿显式登记的边走；c 没登记自己的出处 →
  missingLink=true（中间环节缺失，不猜测）；
- 重复边 409；自环 422；分叉全列出（不选边猜主链）；环如实报告；
- 隔离：A 登记的边对 B 的链条不可见（真实 RoutingDatabase per-user 库）。
"""

from new231_helpers import ab_session


def _edge(client, from_ref: str, to_ref: str) -> dict:
    response = client.post(
        "/api/v1/citation-edges", json={"fromRef": from_ref, "toRef": to_ref, "note": ""}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_new246_chain_trace_and_missing_links(client):
    """a→b→c：链条走显式边；c 无出边 = 中间环节缺失。"""
    _edge(client, "doc:a", "doc:b")
    _edge(client, "doc:b", "doc:c")

    chain = client.get("/api/v1/citation-chain", params={"ref": "doc:a"})
    assert chain.status_code == 200, chain.text
    body = chain.json()
    assert body["startRef"] == "doc:a"
    assert body["cycle"] is False
    nodes = body["chain"]
    assert [n["ref"] for n in nodes] == ["doc:a", "doc:b", "doc:c"]
    assert nodes[0]["missingLink"] is False
    assert nodes[0]["edges"][0]["toRef"] == "doc:b"
    assert nodes[1]["edges"][0]["toRef"] == "doc:c"
    # c 没有登记它引用了什么 → 诚实缺项
    assert nodes[2]["missingLink"] is True
    assert nodes[2]["edges"] == []

    # 起点 自己没登记引用 → 链就一层，missingLink=false（起点不是中间环节）
    empty = client.get("/api/v1/citation-chain", params={"ref": "doc:lonely"})
    assert empty.status_code == 200
    assert empty.json()["chain"][0]["ref"] == "doc:lonely"
    assert empty.json()["chain"][0]["missingLink"] is False
    assert empty.json()["chain"][0]["edges"] == []

    # 边台账 & 解除
    listed = client.get("/api/v1/citation-edges", params={"fromRef": "doc:a"})
    assert len(listed.json()["items"]) == 1
    edge_id = listed.json()["items"][0]["id"]
    removed = client.delete(f"/api/v1/citation-edges/{edge_id}")
    assert removed.status_code == 204
    after = client.get("/api/v1/citation-chain", params={"ref": "doc:a"})
    assert after.json()["chain"][0]["edges"] == []


def test_new246_validation_conflict_fork_cycle(client):
    """自环 422；重复边 409；分叉列出两条边；环 cycle=true。"""
    bad_self = client.post(
        "/api/v1/citation-edges", json={"fromRef": "x", "toRef": "x"}
    )
    assert bad_self.status_code == 422
    assert bad_self.json()["error"]["type"] == "chain_invalid"

    _edge(client, "fork:a", "fork:b")
    dup = client.post("/api/v1/citation-edges", json={"fromRef": "fork:a", "toRef": "fork:b"})
    assert dup.status_code == 409
    assert dup.json()["error"]["type"] == "chain_conflict"

    _edge(client, "fork:a", "fork:c")
    fork = client.get("/api/v1/citation-chain", params={"ref": "fork:a"})
    body = fork.json()
    assert body["chain"][0]["missingLink"] is False
    assert {e["toRef"] for e in body["chain"][0]["edges"]} == {"fork:b", "fork:c"}
    # 分叉不再替用户挑主链：b/c 都有登记，但不继续下钻
    assert len(body["chain"]) == 1

    _edge(client, "loop:b", "loop:a")
    _edge(client, "loop:a", "loop:b")
    cycle = client.get("/api/v1/citation-chain", params={"ref": "loop:a"})
    assert cycle.json()["cycle"] is True

    missing_param = client.get("/api/v1/citation-chain")
    assert missing_param.status_code == 422


def test_new246_isolation_between_users(monkeypatch, tmp_path):
    """A 登记的边对 B 的链条不可见（真实 RoutingDatabase per-user 库）。"""
    with ab_session(monkeypatch, tmp_path) as session:
        member = session.activate_member("n24x-b")
        created = session.client.post(
            "/api/v1/citation-edges", json={"fromRef": "iso:a", "toRef": "iso:b"}, headers=session.owner
        )
        assert created.status_code == 201, created.text

        b_chain = session.client.get(
            "/api/v1/citation-chain", params={"ref": "iso:a"}, headers=member
        )
        assert b_chain.status_code == 200
        assert b_chain.json()["chain"][0]["edges"] == []

        b_edges = session.client.get("/api/v1/citation-edges", headers=member)
        assert b_edges.json()["items"] == []

        a_chain = session.client.get(
            "/api/v1/citation-chain", params={"ref": "iso:a"}, headers=session.owner
        )
        assert a_chain.json()["chain"][0]["edges"][0]["toRef"] == "iso:b"
