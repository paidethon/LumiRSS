"""NEW-204 订阅镜像比对 —— 覆盖差异/单侧失败诚实/抉择台账 + 隔离。

验收问题对照：
- 谁/输入：用户提供两个候选 feed URL（镜像 / 全文 vs 摘要源）；
- 入口：添加来源「镜像比对」（POST /api/v1/new204/compare，只读）；
- 之前/之后：比对前两边各自未定；比对后并排可见每侧最近条目与
  覆盖差异（共有/仅A/仅B，link 精确匹配）；用户确认后落抉择台账
  （pickedSide/pickedUrl），订阅动作走既有 POST /api/v1/subscriptions
  （负向契约：本端点零订阅调用）；
- 失败/恢复：一侧抓取失败 → 该侧 error 字段、另一侧照常、
  comparison=null（诚实于「比不了」）；同 URL 422；
- A/B 隔离：B 的抉择台账 A 不可见。

网络注入：app.state.new204_fetch 假件返回 RSS 文档（零真实网络）。
"""

import pytest
from fastapi.testclient import TestClient

from lumirss.new204_mirror import compare_sides
from lumirss.routers import new204_mirror as mirror_router
from new201_210_harness import feature_app

URL_A = "https://mirror-a.example/feed.xml"
URL_B = "https://mirror-b.example/rss"


def _rss(title, items):
    item_xml = "".join(
        f"<item><title>{t}</title><link>{link}</link>"
        f"<pubDate>Mon, 0{i} Sep 2026 00:00:00 GMT</pubDate></item>"
        for i, (t, link) in enumerate(items, start=1)
    )
    return (
        f'<?xml version="1.0"?><rss version="2.0"><channel><title>{title}</title>'
        f"{item_xml}</channel></rss>"
    ).encode()


@pytest.fixture()
def make_client(tmp_path):
    clients = []

    def _make(*routers, fetch=None):
        app = feature_app(tmp_path, *routers)
        if fetch is not None:
            app.state.new204_fetch = fetch
        client = TestClient(app)
        clients.append(client)
        return client, app

    yield _make
    for client in clients:
        client.close()


def test_new204_compare_sides_pure():
    a = {"comparedEntries": [{"link": "u1"}, {"link": "u2"}, {"link": "u3"}]}
    b = {"comparedEntries": [{"link": "u2"}, {"link": "u3"}, {"link": "u9"}]}
    result = compare_sides(a, b)
    assert result["commonCount"] == 2
    assert result["onlyACount"] == 1
    assert result["onlyBCount"] == 1
    assert compare_sides(a, None) is None


def test_new204_compare_endpoint_overlap_and_side_failure(make_client):
    async def fake_fetch(url):
        if url == URL_A:
            return type(
                "Doc",
                (),
                {
                    "body": _rss(
                        "镜像 A",
                        [
                            ("文章一", "https://x.example/1"),
                            ("文章二", "https://x.example/2"),
                        ],
                    )
                },
            )()
        if url == URL_B:
            return type(
                "Doc",
                (),
                {
                    "body": _rss(
                        "镜像 B",
                        [
                            ("文章二(全文)", "https://x.example/2"),
                            ("文章三", "https://x.example/3"),
                        ],
                    )
                },
            )()
        raise AssertionError(f"意外 URL：{url}")

    client, _app = make_client(mirror_router.router, fetch=fake_fetch)
    result = client.post(
        "/api/v1/new204/compare", json={"urlA": URL_A, "urlB": URL_B}
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["sideA"]["title"] == "镜像 A"
    assert body["sideA"]["entryCount"] == 2
    assert body["comparison"]["commonCount"] == 1  # /2 两侧都有
    assert body["comparison"]["onlyACount"] == 1  # /1 仅 A
    assert body["comparison"]["onlyBCount"] == 1  # /3 仅 B
    assert "不代订" in body["note"]

    # 同 URL → 422 稳定信封
    same = client.post("/api/v1/new204/compare", json={"urlA": URL_A, "urlB": URL_A})
    assert same.status_code == 422
    assert same.json()["error"]["type"] == "mirror_same_url"

    # 一侧失败：另一侧照常摘要，comparison=null（诚实）
    async def broken_b(url):
        if url == URL_A:
            return type("Doc", (), {"body": _rss("镜像 A", [("一", "https://x/1")])})()
        raise RuntimeError("connection refused")

    client2, _app2 = make_client(mirror_router.router, fetch=broken_b)
    degraded = client2.post(
        "/api/v1/new204/compare", json={"urlA": URL_A, "urlB": URL_B}
    ).json()
    assert degraded["sideA"]["entryCount"] == 1
    assert "connection refused" in degraded["sideB"]["error"]
    assert degraded["comparison"] is None


def test_new204_choice_record_and_isolation(make_client):
    client, _app = make_client(mirror_router.router, fetch=None)
    created = client.post(
        "/api/v1/new204/choices",
        json={"urlA": URL_A, "urlB": URL_B, "picked": "B", "note": "B 是全文源"},
    )
    assert created.status_code == 201, created.text
    choice = created.json()
    assert choice["pickedUrl"] == URL_B
    assert "subscriptions" in choice["note"]

    listing = client.get("/api/v1/new204/choices").json()
    assert [c["id"] for c in listing["items"]] == [choice["id"]]

    # 非法 picked → 422
    bad = client.post(
        "/api/v1/new204/choices",
        json={"urlA": URL_A, "urlB": URL_B, "picked": "C"},
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["type"] == "invalid_mirror_choice"

    # A/B 隔离：B 的台账 A 不可见（各自只看到自己的）
    bob = {"x-test-user": "bob"}
    created_b = client.post(
        "/api/v1/new204/choices",
        json={"urlA": URL_A, "urlB": URL_B, "picked": "A"},
        headers=bob,
    )
    assert created_b.status_code == 201
    owner_rows = client.get("/api/v1/new204/choices").json()["items"]
    assert [c["id"] for c in owner_rows] == [choice["id"]], "A 看不到 B 的抉择"
    mine = client.get("/api/v1/new204/choices", headers=bob).json()["items"]
    assert [c["id"] for c in mine] == [created_b.json()["id"]]
