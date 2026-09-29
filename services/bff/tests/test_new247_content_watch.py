"""NEW-247 原文变动关注 — 关注 / 显式哈希检测 / 差异入口 + 隔离。

- 关注（基线正文 + sha256）→ 提交相同正文 → 仍 watching（计数+1）；
  提交不同正文 → changed（当前正文存下）→ diff 入口给出段落级差异；
- watching 时请求差异 → 409（诚实：还没检测到变化）；
- 重复关注 409；没有关注 404；取消后再查 404；
- 隔离：A 的关注对 B 是 404（真实 RoutingDatabase per-user 库）。
"""

from new231_helpers import ab_session

_BASELINE = "第一段保持。\n\n第二段会被改。\n"
_CHANGED = "第一段保持。\n\n第二段已经面目全非。\n\n多出来的新段。\n"


def test_new247_watch_detect_change_and_diff(client):
    """watch → 相同文本 watching → 不同文本 changed → diff 入口。"""
    ref = "e1.watch-item"
    watch = client.post(
        f"/api/v1/entries/{ref}/content-watch", json={"baselineText": _BASELINE}
    )
    assert watch.status_code == 201, watch.text
    body = watch.json()
    assert body["status"] == "watching"
    assert len(body["baselineSha256"]) == 64

    # 相同正文 → 仍 watching，检测计数 +1
    same = client.post(f"/api/v1/entries/{ref}/content-watch/check", json={"currentText": _BASELINE})
    assert same.status_code == 200
    assert same.json()["changed"] is False
    status = client.get(f"/api/v1/entries/{ref}/content-watch")
    assert status.json()["status"] == "watching"
    assert status.json()["checksCount"] == 1
    assert status.json()["lastCheckedAt"]

    # watching 时差异入口 → 409（没有变化可差异）
    early = client.get(f"/api/v1/entries/{ref}/content-watch/diff")
    assert early.status_code == 409
    assert early.json()["error"]["type"] == "content_watch_not_changed"

    # 不同正文 → changed
    check = client.post(
        f"/api/v1/entries/{ref}/content-watch/check", json={"currentText": _CHANGED}
    )
    assert check.status_code == 200
    assert check.json()["changed"] is True
    assert check.json()["status"] == "changed"

    # 差异入口：基线 vs 检测到的当前
    diff = client.get(f"/api/v1/entries/{ref}/content-watch/diff")
    assert diff.status_code == 200, diff.text
    body = diff.json()
    assert body["identical"] is False
    # 两段相似度不足 → 诚实拆成删+增（不硬凑「修改」）
    assert body["removed"] >= 1
    assert body["added"] >= 2
    texts = " ".join(str(block.get("text", "")) + str(block.get("newText", "")) for block in body["blocks"])
    assert "面目全非" in texts

    # 重复关注 → 409
    again = client.post(
        f"/api/v1/entries/{ref}/content-watch", json={"baselineText": _BASELINE}
    )
    assert again.status_code == 409

    # 取消关注 → 404
    unwatch = client.delete(f"/api/v1/entries/{ref}/content-watch")
    assert unwatch.status_code == 204
    gone = client.get(f"/api/v1/entries/{ref}/content-watch")
    assert gone.status_code == 404


def test_new247_validation_and_missing(client):
    empty = client.post("/api/v1/entries/e1.x/content-watch", json={"baselineText": " "})
    assert empty.status_code == 422

    check_missing = client.post(
        "/api/v1/entries/e1.x/content-watch/check", json={"currentText": "正文"}
    )
    assert check_missing.status_code == 404

    diff_missing = client.get("/api/v1/entries/e1.x/content-watch/diff")
    assert diff_missing.status_code == 404
    assert diff_missing.json()["error"]["type"] == "content_watch_not_found"


def test_new247_isolation_between_users(monkeypatch, tmp_path):
    """A 的关注对 B 是 404（真实 RoutingDatabase per-user 库）。"""
    with ab_session(monkeypatch, tmp_path) as session:
        member = session.activate_member("n24x-b")
        ref = "e1.iso-watch"
        watch = session.client.post(
            f"/api/v1/entries/{ref}/content-watch",
            json={"baselineText": "A 的基线正文。"},
            headers=session.owner,
        )
        assert watch.status_code == 201, watch.text

        b_status = session.client.get(f"/api/v1/entries/{ref}/content-watch", headers=member)
        assert b_status.status_code == 404

        b_check = session.client.post(
            f"/api/v1/entries/{ref}/content-watch/check",
            json={"currentText": "B 提交的正文。"},
            headers=member,
        )
        assert b_check.status_code == 404

        a_status = session.client.get(f"/api/v1/entries/{ref}/content-watch", headers=session.owner)
        assert a_status.status_code == 200
