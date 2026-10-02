"""R18 — OPML 导入自动发现并使用 RSSHub：匹配 / 验证 / 替换 / 映射。

全部上游网络 mock（httpx.MockTransport 假 RSSHub 实例；控制适配器是
录制的 fake）。真实拉取（BFF → rsshub:1200 内网）与 FreshRSS greader
实际订阅留给集成验收（部署栈内验证，本文件不触网）。

覆盖：已是 RSSHub（本站/外部实例）、唯一高置信自动、多候选人工、
缺参数（人工指定不可构造路由 → 跳过）、缺凭据不静默替换、不支持
站点、prefer_native 保留原生、同域多路由消歧降级、保留旧源 +
关联新源（批注表不动的诚实边界）、验证失败回落原生、映射台账
（list / revert / 404 / 幂等）。
"""

import asyncio
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from lumirss.adapters.freshrss_control import Subscription
from lumirss.main import app
from lumirss.opml import parse_opml
from lumirss.rsshub import RssHubService
from lumirss.rsshub_import_flow import RsshubImportService, strategy_or_none
from lumirss.rsshub_match import (
    MissingRouteParams,
    instantiate_route,
    match_source,
)
from lumirss.rsshub_source_mapping import RsshubSourceMappingStore
from lumirss.storage import Database

SELF_ORIGIN = "http://rsshub:1200"
BFF_ORIGIN = "http://127.0.0.1:1200"
ORIGINS = (SELF_ORIGIN, BFF_ORIGIN)

RSS_DOC = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Fake RSSHub Feed</title><link>https://example.com/</link>
  <description>d</description><item><title>e1</title></item>
</channel></rss>"""

OPML = """<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0"><body>
  <outline text="少数派">
    <outline text="Matrix" xmlUrl="https://sspai.com/matrix" htmlUrl="https://sspai.com" />
  </outline>
  <outline text="热榜">
    <outline text="36kr 热榜" xmlUrl="https://36kr.com/hot-list" />
  </outline>
  <outline text="知乎">
    <outline text="动态" xmlUrl="https://www.zhihu.com/people/activities/someone" />
  </outline>
  <outline text="未知">
    <outline text="博客" xmlUrl="https://blog.example.com/rss" />
  </outline>
  <outline text="外站">
    <outline text="外部实例" xmlUrl="https://rsshub.app/sspai/index" />
  </outline>
  <outline text="本站">
    <outline text="已在本站" xmlUrl="http://rsshub:1200/sspai/series" />
  </outline>
</body></opml>""".encode()

# 假实例只会对以下路径吐有效 feed；其余一律 404（验证失败路径）。
OK_PATHS = {"/sspai/matrix", "/sspai/index", "/sspai/series", "/36kr/newsflashes"}


def run(coroutine):
    return asyncio.run(coroutine)


def make_rsshub_service(fetched: list[str] | None = None) -> RssHubService:
    """假 RSSHub 实例（MockTransport；load_settings 用替身注入）。"""

    class FakeSettings:
        RSSHUB_BASE_URL = BFF_ORIGIN
        RSSHUB_FRESHRSS_BASE_URL = SELF_ORIGIN

        @property
        def freshrss_base_url(self) -> str:
            return SELF_ORIGIN

    def handler(request: httpx.Request) -> httpx.Response:
        if fetched is not None:
            fetched.append(request.url.path)
        path = request.url.path
        if path in OK_PATHS or re.fullmatch(r"/sspai/column/\d+", path):
            return httpx.Response(
                200, content=RSS_DOC, headers={"content-type": "application/rss+xml"}
            )
        return httpx.Response(404, content=b"nope")

    service = RssHubService(
        httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0),
        control=None,
    )
    service.load_settings = lambda: FakeSettings()  # type: ignore[method-assign]
    return service


class FakeControl:
    """录制式控制适配器（订阅状态机，最小面）。"""

    def __init__(self, existing_urls=()) -> None:
        self.next_id = 100
        self.subscriptions = [
            Subscription(stream_id=f"feed/{i + 1}", title=url, feed_url=url)
            for i, url in enumerate(existing_urls)
        ]
        self.categories: list[tuple[str, str]] = []

    async def list_subscriptions(self):
        return list(self.subscriptions)

    async def list_categories(self):
        return []

    async def subscribe(self, feed_url, *, category_id=None, title=None):
        self.next_id += 1
        subscription = Subscription(
            stream_id=f"feed/{self.next_id}",
            title=title or feed_url,
            feed_url=feed_url,
        )
        self.subscriptions.append(subscription)
        return subscription

    async def move_to_new_category(self, stream_id, label):
        self.categories.append((stream_id, label))

    async def move_category(self, stream_id, category_id):
        self.categories.append((stream_id, category_id))


def make_service(existing=(), db=None) -> tuple[RsshubImportService, FakeControl]:
    """默认自带临时每用户库（映射台账落在真实 SQLite 迁移上）。"""
    control = FakeControl(existing_urls=existing)
    if db is None:
        import tempfile

        db = Database(f"{tempfile.mkdtemp()}/lumi.sqlite")
    return RsshubImportService(control, make_rsshub_service(), db=db), control


def decisions(plan: dict) -> dict[int, str]:
    return {item["index"]: item["decision"] for item in plan["items"]}


# ---- 匹配器（纯函数） --------------------------------------------------------


def test_matcher_self_rsshub_needs_no_replacement():
    outcome = match_source("http://rsshub:1200/sspai/matrix", None, ORIGINS)
    assert outcome.kind == "self_rsshub"
    assert outcome.auto_route_path is None


def test_matcher_external_instance_rewrites_to_local():
    outcome = match_source("https://rsshub.app/sspai/index", None, ORIGINS)
    assert outcome.kind == "external_rsshub"
    assert outcome.auto_route_path == "/sspai/index"


def test_matcher_unique_high_confidence_is_auto():
    outcome = match_source("https://sspai.com/matrix", "https://sspai.com", ORIGINS)
    assert outcome.kind == "native"
    assert outcome.auto_route_path == "/sspai/matrix"
    high = [c for c in outcome.candidates if c.confidence == "high"]
    assert len(high) == 1 and high[0].route_path == "/sspai/matrix"


def test_matcher_same_domain_multi_route_demotes_to_manual():
    """/hot-list 同时被两条 36kr 路由解释 → 全部降级 medium + 人工。"""
    outcome = match_source("https://36kr.com/hot-list", None, ORIGINS)
    assert outcome.auto_route_path is None
    assert outcome.note is not None and "人工" in outcome.note
    assert any(c.ambiguous for c in outcome.candidates)
    assert all(c.confidence != "high" for c in outcome.candidates)


def test_matcher_credentials_required_blocks_auto():
    outcome = match_source(
        "https://www.zhihu.com/people/activities/someone", None, ORIGINS
    )
    assert outcome.auto_route_path is None
    high = [c for c in outcome.candidates if c.confidence == "high"]
    assert len(high) == 1 and high[0].needs_credentials
    assert "凭据" in (outcome.note or "")


def test_matcher_unsupported_site_keeps_native():
    outcome = match_source("https://blog.example.com/rss", None, ORIGINS)
    assert outcome.kind == "unknown"
    assert outcome.candidates == ()
    assert outcome.auto_route_path is None


def test_instantiate_route_fills_optional_drops_and_encodes():
    assert (
        instantiate_route("/36kr/:category/:subCategory?/:keyword?", {"category": "newsflashes"})
        == "/36kr/newsflashes"
    )
    assert instantiate_route("/sspai/tag/:keyword", {"keyword": "a b"}) == "/sspai/tag/a%20b"
    with pytest.raises(MissingRouteParams):
        instantiate_route("/sspai/tag/:keyword", {})


def test_strategy_default_and_invalid():
    assert strategy_or_none(None) == "prefer_rsshub"
    assert strategy_or_none("manual") == "manual"
    assert strategy_or_none("bogus") is None


# ---- plan / apply（服务层，mock 实例 + fake 控制） ----------------------------


def test_plan_reports_every_decision_kind():
    service, _ = make_service()
    plan = service.plan(parse_opml(OPML))
    assert plan["rsshubConfigured"] is True
    assert decisions(plan) == {
        0: "autoReplace",  # sspai.com/matrix 唯一高置信
        1: "manualChoice",  # 36kr hot-list 同域多路由
        2: "needsCredentials",  # zhihu 需 cookies
        3: "keepNative",  # 不支持站点
        4: "autoReplace",  # 外部实例 → 本站
        5: "alreadyRsshub",  # 已是本站地址
    }
    # 计划只回显路径与用户输入，不携带配置的实例 base（候选全为路径）。
    for item in plan["items"]:
        for candidate in item["match"]["candidates"]:
            assert SELF_ORIGIN not in candidate["routePath"]


@pytest.mark.anyio
async def test_apply_prefer_rsshub_replaces_and_validates():
    service, control = make_service()
    result = await service.apply(parse_opml(OPML), strategy="prefer_rsshub", approved_indexes=None)

    urls = {s.feed_url for s in control.subscriptions}
    # 替换：验证通过后订阅本站实例地址（原始地址不订阅，进台账）
    assert "http://rsshub:1200/sspai/matrix" in urls
    assert "https://sspai.com/matrix" not in urls
    assert "http://rsshub:1200/sspai/index" in urls  # 外部实例改本站
    assert "https://rsshub.app/sspai/index" not in urls
    # 原生保留：36kr 人工候选 / zhihu 需凭据 / 未知站点 → 原样导入
    assert {"https://36kr.com/hot-list", "https://www.zhihu.com/people/activities/someone",
            "https://blog.example.com/rss"} <= urls
    # 已是本站地址的条目按原地址导入
    assert "http://rsshub:1200/sspai/series" in urls

    assert result["counts"]["replaced"] == 2
    assert len(result["mappings"]) == 2
    assert all(m["keptOldSource"] is False for m in result["mappings"])
    assert "无法跨源安全迁移" in result["entryStateNote"]


@pytest.mark.anyio
async def test_apply_keeps_old_source_when_original_already_subscribed(tmp_path):
    """原 URL 已订阅：新增 RSSHub 源 + 台账关联，绝不退订旧源。"""
    import tempfile

    db = Database(f"{tempfile.mkdtemp()}/lumi.sqlite")
    service, control = make_service(existing=["https://sspai.com/matrix"], db=db)
    opml = b"""<opml><body><outline text="M" xmlUrl="https://sspai.com/matrix" /></body></opml>"""
    result = await service.apply(parse_opml(opml), strategy="prefer_rsshub", approved_indexes=None)

    urls = {s.feed_url for s in control.subscriptions}
    assert "https://sspai.com/matrix" in urls  # 旧源保留
    assert "http://rsshub:1200/sspai/matrix" in urls  # 新源并存
    assert result["counts"]["keptOldSource"] == 1
    assert result["replaced"][0]["keptOldSource"] is True
    mapping = await RsshubSourceMappingStore(db).list_all()
    assert mapping[0]["keptOldSource"] is True
    assert mapping[0]["status"] == "active"


@pytest.mark.anyio
async def test_apply_validation_failure_falls_back_to_native():
    """/huxiu/article 返回 404：验证失败 → 新导入项回落原生并如实报告。"""
    service, control = make_service()
    opml = """<opml><body><outline text="虎嗅" xmlUrl="https://huxiu.com/article" /></body></opml>""".encode()
    result = await service.apply(parse_opml(opml), strategy="prefer_rsshub", approved_indexes=None)

    assert result["counts"]["replaced"] == 0
    assert len(result["addedNative"]) == 1
    assert result["addedNative"][0]["reason"] == "rsshub_not_found"
    urls = {s.feed_url for s in control.subscriptions}
    assert "https://huxiu.com/article" in urls
    assert "http://rsshub:1200/huxiu/article" not in urls


@pytest.mark.anyio
async def test_apply_validation_failure_never_silently_redirects_manual():
    """manual 显式选择的项验证失败 → failed，绝不静默改订原生。"""
    service, control = make_service()
    opml = """<opml><body><outline text="虎嗅" xmlUrl="https://huxiu.com/article" /></body></opml>""".encode()
    result = await service.apply(
        parse_opml(opml), strategy="manual", approved_indexes={0},
        chosen_map={0: "/huxiu/article"},
    )

    assert result["counts"]["failed"] == 1
    assert result["failed"][0]["error"] == "rsshub_not_found"
    assert control.subscriptions == []  # 什么都没订阅


@pytest.mark.anyio
async def test_apply_manual_with_params_missing_route_skips_and_imports_native():
    """人工指定带必填参数的路由但无法从地址推导参数 → 跳过 + 原生导入。"""
    service, control = make_service()
    opml = """<opml><body><outline text="少数派标签订阅" xmlUrl="https://sspai.com/tag" /></body></opml>""".encode()
    result = await service.apply(
        parse_opml(opml), strategy="manual", approved_indexes={0},
        chosen_map={0: "/sspai/tag/:keyword"},
    )

    assert result["counts"]["replaced"] == 0
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["reason"] == "route_not_constructable"
    assert {s.feed_url for s in control.subscriptions} == {"https://sspai.com/tag"}


@pytest.mark.anyio
async def test_apply_manual_rejects_paths_outside_plan():
    """chosen 不在计划候选内 → 拒绝（不能注入任意路径）。"""
    service, control = make_service()
    opml = b"""<opml><body><outline text="S" xmlUrl="https://sspai.com/matrix" /></body></opml>"""
    result = await service.apply(
        parse_opml(opml), strategy="manual", approved_indexes={0},
        chosen_map={0: "/36kr/newsflashes"},
    )
    assert result["counts"]["replaced"] == 0
    assert result["skipped"][0]["reason"] == "route_not_in_plan"


@pytest.mark.anyio
async def test_apply_prefer_native_never_touches_rsshub():
    fetched: list[str] = []
    control = FakeControl()
    service = RsshubImportService(control, make_rsshub_service(fetched), db=None)
    result = await service.apply(parse_opml(OPML), strategy="prefer_native", approved_indexes=None)

    assert fetched == []  # 一次实例拉取都没有
    assert result["counts"]["replaced"] == 0
    assert result["counts"]["addedNative"] == 6
    assert result["mappings"] == []


@pytest.mark.anyio
async def test_apply_validation_budget_bounds_instance_fetches():
    """验证预算有界：超过 MAX_VALIDATIONS 的替换项如实跳过，不做无界扇出。"""
    from lumirss.rsshub_import_flow import MAX_VALIDATIONS

    fetched: list[str] = []
    control = FakeControl()
    service = RsshubImportService(control, make_rsshub_service(fetched), db=None)
    outlines = "".join(
        f'<outline text="s{i}" xmlUrl="https://sspai.com/column/{i}" />' for i in range(MAX_VALIDATIONS + 5)
    )
    opml = f"<opml><body>{outlines}</body></opml>".encode()
    result = await service.apply(parse_opml(opml), strategy="prefer_rsshub", approved_indexes=None)

    # sspai/column/:id 是高置信候选；预算内验证 + 替换，其余跳过
    assert len(fetched) <= MAX_VALIDATIONS
    assert result["counts"]["replaced"] == MAX_VALIDATIONS
    assert sum(1 for s in result["skipped"] if s["reason"] == "validation_budget_exhausted") == 5


# ---- 路由层（TestClient + 注入 fake；台账走真实 Lumi SQLite） --------------------


@pytest.fixture()
def r18_client(tmp_path):
    control = FakeControl(existing_urls=["https://keep.example/rss"])
    service = RsshubImportService(control, make_rsshub_service(), db=None)
    with TestClient(app) as test_client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        app.state.freshrss_control_adapter = control
        app.state.rsshub_service = make_rsshub_service()
        # 路由层从 deps 拿 RsshubImportService 的两个依赖：直接替换
        # app.state 上被 _cached_on_app_state 优先读取的实例即可。
        test_client.extra = {"service": service}
        yield test_client, control
    app.state.freshrss_control_adapter = None
    app.state.rsshub_service = None


def test_route_plan_and_apply_roundtrip(r18_client, tmp_path):
    client, control = r18_client
    plan = client.post("/api/v1/opml/import/rsshub-plan", content=OPML)
    assert plan.status_code == 200
    body = plan.json()
    assert body["rsshubConfigured"] is True
    assert decisions(body)[0] == "autoReplace"

    # plan 无副作用：只解析，不写库不订阅
    assert {s.feed_url for s in control.subscriptions} == {"https://keep.example/rss"}

    applied = client.post(
        "/api/v1/opml/import/rsshub-apply?strategy=prefer_rsshub", content=OPML
    )
    assert applied.status_code == 200
    result = applied.json()
    assert result["counts"]["replaced"] == 2
    assert len(result["mappings"]) == 2
    assert "无法跨源安全迁移" in result["entryStateNote"]

    urls = {s.feed_url for s in control.subscriptions}
    assert "http://rsshub:1200/sspai/matrix" in urls
    assert "https://sspai.com/matrix" not in urls


def test_route_mapping_list_revert_and_404(r18_client):
    client, control = r18_client
    applied = client.post(
        "/api/v1/opml/import/rsshub-apply?strategy=prefer_rsshub", content=OPML
    )
    mapping_id = applied.json()["mappings"][0]["id"]

    listed = client.get("/api/v1/opml/rsshub-mappings")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 2
    assert items[0]["status"] == "active"

    missing = client.post("/api/v1/opml/rsshub-mappings/nope/revert")
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "mapping_not_found"

    reverted = client.post(f"/api/v1/opml/rsshub-mappings/{mapping_id}/revert")
    assert reverted.status_code == 200
    assert reverted.json()["mapping"]["status"] == "reverted"
    assert reverted.json()["rsshubSourceRemoved"] is False
    # 撤销 = 原地址重新可订阅（fake 控制里出现），RSSHub 源不自动退订
    original_url = reverted.json()["mapping"]["originalUrl"]
    assert any(s.feed_url == original_url for s in control.subscriptions)

    # 幂等：再次撤销原样返回
    again = client.post(f"/api/v1/opml/rsshub-mappings/{mapping_id}/revert")
    assert again.status_code == 200
    assert again.json()["mapping"]["status"] == "reverted"


def test_route_apply_rejects_invalid_strategy(r18_client):
    client, _ = r18_client
    response = client.post(
        "/api/v1/opml/import/rsshub-apply?strategy=bogus", content=OPML
    )
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_strategy"


def test_route_apply_rejects_malformed_chosen(r18_client):
    client, _ = r18_client
    response = client.post(
        "/api/v1/opml/import/rsshub-apply?strategy=manual&approved=0&chosen=0bad",
        content=OPML,
    )
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_selection"
