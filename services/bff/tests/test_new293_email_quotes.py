"""NEW-293 邮件引用折叠 — 分段启发式 / 折叠口径 / 逐段核对 / 隔离。"""

from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.new293_email_quotes import split_segments
from lumirss.storage import Database
from new2xx_ab import ab_env  # noqa: F401,F811 — pytest 夹具注册

_BODY = (
    "这是我的新回复，直接回答你的问题。\n"
    "结论：可以。\n"
    "> 你上周问：排期定在什么时候？\n"
    "> 我当时的建议是先做调研。\n"
    "> 后续再定执行日期。\n"
    "另外附上会议纪要。\n"
    "> 旧线程里的重复引用内容，一长串。\n"
    "> 第二行旧引用。"
)


def _import_one(client: TestClient, mid: str = "<q293@example.test>") -> str:
    eml = (
        f"Message-ID: {mid}\r\n"
        f"From: a@example.test\r\n"
        f"Subject: 引用折叠样本\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n\r\n{_BODY}\r\n"
    )
    result = client.post(
        "/api/v1/email-materials/import",
        json={"files": [{"filename": "quote.eml", "content": eml}]},
    )
    assert result.status_code == 200, result.text
    return result.json()["imported"][0]["id"]


def test_new293_split_segments_prefix_heuristic():
    """单元：连续 "> " 行合并为 quoted 段，其余为 own 段，序号稳定。"""
    segments = split_segments(_BODY)
    kinds = [s["kind"] for s in segments]
    assert kinds == ["own", "quoted", "own", "quoted"]
    assert segments[0]["text"].startswith("这是我的新回复")
    assert segments[1]["lines"] == 3
    assert [s["index"] for s in segments] == [0, 1, 2, 3]


def test_new293_segments_view_folds_quotes_and_reports_honestly():
    """视图：引用段如实计数并标注需折叠；honesty 说明启发式边界。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        material_id = _import_one(client)
        view = client.get(
            f"/api/v1/email-materials/{material_id}/quote-segments"
        ).json()
        assert view["quotedCount"] == 2
        assert view["quotedLines"] == 5
        assert view["reviewedCount"] == 0
        assert all(s["reviewed"] is False for s in view["segments"])
        assert "行前缀" in view["honestyNote"]
        # 原文完整可取（折叠只影响阅读视图）
        detail = client.get(f"/api/v1/email-materials/{material_id}").json()
        assert "旧线程里的重复引用内容" in detail["bodyText"]


def test_new293_review_marks_quoted_segments_only():
    """核对：引用段可标已核对；own 段 422；越界 404；重复标记幂等。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        material_id = _import_one(client)

        ok = client.post(
            f"/api/v1/email-materials/{material_id}/quote-reviews",
            json={"segmentIndex": 1},
        )
        assert ok.status_code == 200, ok.text
        body = ok.json()
        assert body["segments"][1]["reviewed"] is True
        assert body["reviewedCount"] == 1

        # 幂等重复标记
        again = client.post(
            f"/api/v1/email-materials/{material_id}/quote-reviews",
            json={"segmentIndex": 1},
        )
        assert again.status_code == 200
        assert again.json()["reviewedCount"] == 1

        own = client.post(
            f"/api/v1/email-materials/{material_id}/quote-reviews",
            json={"segmentIndex": 0},
        )
        assert own.status_code == 422
        assert own.json()["error"]["type"] == "quote_segment_not_quoted"

        missing = client.post(
            f"/api/v1/email-materials/{material_id}/quote-reviews",
            json={"segmentIndex": 99},
        )
        assert missing.status_code == 404


def test_new293_cross_user_reviews_isolated(ab_env):  # noqa: F811
    """A 的核对状态对 B 不可见（per-user 库）。"""
    env = ab_env
    client = env["client"]

    def upload(who: dict[str, str]) -> str:
        eml = (
            "Message-ID: <iso-q@example.test>\r\n"
            "From: a@example.test\r\n"
            "Subject: 各自导入\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n\r\n"
            "我的新话。\n> 旧引用一段。\r\n"
        )
        result = client.post(
            "/api/v1/email-materials/import",
            json={"files": [{"filename": "q.eml", "content": eml}]},
            headers=who,
        )
        assert result.status_code == 200, result.text
        return result.json()["imported"][0]["id"]

    a_id = upload(env["a"])
    b_id = upload(env["b"])

    marked = client.post(
        f"/api/v1/email-materials/{a_id}/quote-reviews",
        json={"segmentIndex": 1},
        headers=env["a"],
    )
    assert marked.status_code == 200, marked.text
    assert marked.json()["reviewedCount"] == 1

    view_b = client.get(
        f"/api/v1/email-materials/{b_id}/quote-segments", headers=env["b"]
    ).json()
    assert view_b["reviewedCount"] == 0
    # A 的标记对 A 自己仍可见
    view_a = client.get(
        f"/api/v1/email-materials/{a_id}/quote-segments", headers=env["a"]
    ).json()
    assert view_a["reviewedCount"] == 1


def _tmp() -> str:
    import tempfile

    return tempfile.mkdtemp()
