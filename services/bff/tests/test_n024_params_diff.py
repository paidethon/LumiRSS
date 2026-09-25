"""N024 路由变更差异预览 —— 新旧参数两侧有界抓取 + 标题级 diff（只读）。

- diff 语义：added = 仅新 feed 有的标题 / removed = 仅旧有的 /
  duplicates = 两侧都有（标题为对照键——entry id 不跨参数稳定）；
- 一侧抓取失败 → 该侧 error 如实说明，diff 基于可用一侧诚实计算；
- 端点零写入（对照期间订阅状态逐字节不变——「取消不产生任何变更」
  的服务端基础；Web 侧确认才走既有迁移端点）。
"""

from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.rsshub import (
    RssHubPreviewCache,
    RssHubService,
    diff_title_sets,
    extract_entry_titles,
)
from lumirss.storage import Database

BASE_URL = "http://rsshub.test:1200"

OLD_DOC = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Old</title>
  <item><title>alpha</title></item>
  <item><title>shared</title></item>
</channel></rss>"""

NEW_DOC = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>New</title>
  <item><title>beta</title></item>
  <item><title>shared</title></item>
  <item><title>gamma</title></item>
</channel></rss>"""


class FakeSettings:
    def __init__(self) -> None:
        self.RSSHUB_BASE_URL = BASE_URL
        self.RSSHUB_FRESHRSS_BASE_URL = ""

    @property
    def freshrss_base_url(self) -> str:
        return self.RSSHUB_FRESHRSS_BASE_URL or self.RSSHUB_BASE_URL


def _service(doc_by_path: dict[str, bytes]) -> RssHubService:
    def handler(request: httpx.Request) -> httpx.Response:
        for path, doc in doc_by_path.items():
            if request.url.path == path:
                return httpx.Response(200, content=doc)
        return httpx.Response(404, content=b"nope")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def _list():
        return []

    service = RssHubService(client, SimpleNamespace(list_subscriptions=_list))
    service.load_settings = lambda: FakeSettings()  # type: ignore[method-assign]
    return service


@pytest.fixture()
def diff_client(tmp_path):
    with TestClient(app) as test_client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        app.state.rsshub_preview_cache = RssHubPreviewCache(ttl_s=0.0)
        yield test_client
    app.state.rsshub_service = None


def test_n024_diff_pure_functions():
    titles = extract_entry_titles(OLD_DOC)
    assert titles == ["alpha", "shared"]
    diff = diff_title_sets(["alpha", "shared"], ["beta", "shared", "gamma"])
    assert diff["added"] == ["beta", "gamma"]
    assert diff["removed"] == ["alpha"]
    assert diff["duplicates"] == ["shared"]
    # 页内重复标题按首现去重（稳定顺序）。
    dup = diff_title_sets(["x", "x"], ["x"])
    assert dup["added"] == []
    assert dup["duplicates"] == ["x"]


def test_n024_params_diff_endpoint_computes_both_sides(diff_client):
    app.state.rsshub_service = _service(
        {"/v2ex/topics/hot": OLD_DOC, "/v2ex/topics/latest": NEW_DOC}
    )
    response = diff_client.post(
        "/api/v1/rsshub/params-diff",
        json={
            "oldFeedUrl": "http://rsshub.test:1200/v2ex/topics/hot?extra=1",
            "routeId": "v2ex-topics",
            "newParams": {"type": "latest"},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["old"]["titles"] == ["alpha", "shared"]
    assert payload["old"]["entryCount"] == 2
    assert payload["new"]["titles"] == ["beta", "shared", "gamma"]
    assert payload["added"] == ["beta", "gamma"]
    assert payload["removed"] == ["alpha"]
    assert payload["duplicates"] == ["shared"]
    # newUrl = FreshRSS 面向订阅地址（构造规则与 preview 一致）。
    assert payload["newUrl"] == f"{BASE_URL}/v2ex/topics/latest"
    assert "取消" in payload["note"]


def test_n024_params_diff_reports_fetch_failure_honestly(diff_client):
    # 旧地址 404 → old 侧 error 如实说明；diff 基于可用一侧（不臆造
    # 「removed 全部」的假差异——old titles 未知时 removed/added 分开看）。
    app.state.rsshub_service = _service({"/v2ex/topics/latest": NEW_DOC})
    response = diff_client.post(
        "/api/v1/rsshub/params-diff",
        json={
            "oldFeedUrl": "http://rsshub.test:1200/v2ex/topics/hot",
            "routeId": "v2ex-topics",
            "newParams": {"type": "latest"},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["old"]["titles"] is None
    assert payload["old"]["error"] is not None
    assert payload["new"]["titles"] == ["beta", "shared", "gamma"]


def test_n024_params_diff_validates_inputs(diff_client):
    app.state.rsshub_service = _service({})
    # 未知路由 → 稳定错误。
    unknown = diff_client.post(
        "/api/v1/rsshub/params-diff",
        json={"oldFeedUrl": "http://rsshub.test:1200/x", "routeId": "nope", "newParams": {}},
    )
    assert unknown.status_code == 404
    # 非法 oldFeedUrl（非 http(s)）→ 稳定错误。
    bad_url = diff_client.post(
        "/api/v1/rsshub/params-diff",
        json={"oldFeedUrl": "ftp://x/y", "routeId": "v2ex-topics", "newParams": {"type": "hot"}},
    )
    assert bad_url.status_code == 400
    # 非法参数（pattern 不符）→ 稳定错误。
    bad_params = diff_client.post(
        "/api/v1/rsshub/params-diff",
        json={"oldFeedUrl": "http://rsshub.test:1200/v2ex/topics/hot", "routeId": "v2ex-topics", "newParams": {"type": "yolo"}},
    )
    assert bad_params.status_code == 400


def test_n024_params_diff_is_read_only(diff_client):
    """对照期间订阅/分类状态零变更——「取消不产生任何变更」的服务端契约。"""
    calls: list[str] = []

    async def _list_subscriptions():
        calls.append("list_subscriptions")
        return []

    service = _service({"/v2ex/topics/hot": OLD_DOC, "/v2ex/topics/latest": NEW_DOC})
    service._control = SimpleNamespace(list_subscriptions=_list_subscriptions)
    app.state.rsshub_service = service
    response = diff_client.post(
        "/api/v1/rsshub/params-diff",
        json={
            "oldFeedUrl": "http://rsshub.test:1200/v2ex/topics/hot",
            "routeId": "v2ex-topics",
            "newParams": {"type": "latest"},
        },
    )
    assert response.status_code == 200
    # diff 路径只读订阅列表（alreadySubscribed 语义沿未使用），绝不触发
    # 任何 mutation 形状的调用（fake 只有读方法，调用即进 calls）。
    assert all(call == "list_subscriptions" for call in calls)
