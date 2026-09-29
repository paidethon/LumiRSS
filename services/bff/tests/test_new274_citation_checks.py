"""NEW-274 AI 结果引用核验 — 逐条定位 / 未定位闸门 / 显式确认。"""

from contextlib import contextmanager

from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.storage import Database
from new2xx_ab import ab_env  # noqa: F401,F811 — pytest 夹具注册
from new271_helpers import (
    FakeAdapter,
    entry_ref,
    item_id_of,
    make_detail,
)

REF_A = entry_ref()
REF_B = entry_ref("tag:google.com,2005:reader/item/0000000000000002")
GHOST = entry_ref("tag:google.com,2005:reader/item/0000000000000003")

CLAIM_PRESENT = "温度每升高十度反应速率大约翻倍"
CLAIM_ABSENT = "这句话在原文里并不存在"


def _adapter():
    return FakeAdapter(
        {
            item_id_of(REF_A): make_detail(
                text=f"实验表明，{CLAIM_PRESENT}。其余细节从略。",
                ref="tag:google.com,2005:reader/item/0000000000000001",
            ),
            item_id_of(REF_B): make_detail(
                text="另一篇文章的正文内容。",
                ref="tag:google.com,2005:reader/item/0000000000000002",
            ),
        }
    )


@contextmanager
def _client(db, adapter):
    with TestClient(app) as client:
        app.state.db = db
        app.state.freshrss_adapter = adapter
        yield client


def test_new274_locate_citations_and_gate():
    """found/not_found/entry_unavailable 混合定位；有未定位时必须确认。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with _client(db, _adapter()) as client:
        check = client.post(
            "/api/v1/ai/citation-checks",
            json={
                "answerText": "根据两篇文章：速率翻倍；另一篇讲城市化。",
                "citations": [
                    {"index": 1, "entryRef": REF_A, "claim": CLAIM_PRESENT},
                    {"index": 2, "entryRef": REF_A, "claim": CLAIM_ABSENT},
                    {"index": 3, "entryRef": GHOST, "claim": "无所谓"},
                ],
            },
        )
        assert check.status_code == 201, check.text
        body = check.json()
        statuses = {c["index"]: c["status"] for c in body["citations"]}
        assert statuses[1] == "found"
        assert statuses[2] == "not_found"
        assert statuses[3] == "entry_unavailable"
        found = body["citations"][0]
        assert CLAIM_PRESENT in found["excerpt"]
        assert found["offset"] >= 0
        assert body["missingCount"] == 2
        assert "字面" in body["honestyNote"]  # 不声称自动核验一切

        # 未确认 → 422（用户确认闸门）
        gated = client.post(
            f"/api/v1/ai/citation-checks/{body['id']}/mark-checked",
            json={},
        )
        assert gated.status_code == 422
        assert gated.json()["error"]["type"] == "citation_confirmation_required"

        confirmed = client.post(
            f"/api/v1/ai/citation-checks/{body['id']}/mark-checked",
            json={"confirmMissing": True},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["checked"] is True
        assert confirmed.json()["confirmedMissing"] is True

        listing = client.get("/api/v1/ai/citation-checks").json()
        assert listing["total"] == 1


def test_new274_all_found_checks_without_confirm():
    """全部定位成功时无需确认即可标为已核对。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with _client(db, _adapter()) as client:
        check = client.post(
            "/api/v1/ai/citation-checks",
            json={
                "answerText": "速率结论。",
                "citations": [
                    {"index": 1, "entryRef": REF_A, "claim": CLAIM_PRESENT}
                ],
            },
        ).json()
        marked = client.post(
            f"/api/v1/ai/citation-checks/{check['id']}/mark-checked", json={}
        )
        assert marked.status_code == 200
        assert marked.json()["checked"] is True
        assert marked.json()["confirmedMissing"] is False


def test_new274_validation():
    """空引用/空 claim → 422；未知核验 → 404。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with _client(db, _adapter()) as client:
        bad = client.post(
            "/api/v1/ai/citation-checks",
            json={"answerText": "x", "citations": []},
        )
        assert bad.status_code == 422
        no_claim = client.post(
            "/api/v1/ai/citation-checks",
            json={"answerText": "x", "citations": [{"index": 1, "entryRef": REF_A}]},
        )
        assert no_claim.status_code == 422
        assert (
            client.get("/api/v1/ai/citation-checks/no-such").status_code == 404
        )


def test_new274_cross_user_checks_isolated(ab_env):  # noqa: F811
    """A 的核验台账对 B 不可见。"""
    env = ab_env
    client = env["client"]
    app.state.freshrss_adapter = _adapter()
    check = client.post(
        "/api/v1/ai/citation-checks",
        json={
            "answerText": "A 的回答",
            "citations": [
                {"index": 1, "entryRef": REF_A, "claim": CLAIM_ABSENT}
            ],
        },
        headers=env["a"],
    )
    assert check.status_code == 201, check.text
    assert (
        client.get("/api/v1/ai/citation-checks", headers=env["b"]).json()["total"]
        == 0
    )
    assert (
        client.get(
            f"/api/v1/ai/citation-checks/{check.json()['id']}", headers=env["b"]
        ).status_code
        == 404
    )


def _tmp() -> str:
    import tempfile

    return tempfile.mkdtemp()
