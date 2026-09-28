"""FIX-362 — 错误响应 Content-Type 与正文不符（上游 HTML 不得伪装成功）。

判定：BASELINE_OK（逐条错误路径核验 + HTTP 级验证性测试）。代理
上游响应的错误路径全部走「类型化异常 → 稳定 JSON 错误信封」，
没有任何一条会把上游 HTML 以 200 或错标 Content-Type 透传给期望
JSON 的前端：

- FreshRSS 读路径（adapters/freshrss.py ``_authorized_get_json``）：
  非 200 → UpstreamError；200 但响应体非 JSON（例如反代返回的 HTML
  错误页）→ 同样 UpstreamError——正文永不透传；
- API 源 fetch（api_sources.py ``fetch_json``）：content-type 不含
  json → ApiSourceFetchFailed（200+HTML 在读体之前即拒绝）；
- AI provider（ai_provider.py）：``_map_status`` 按状态码抛稳定错误族
  （正文不转发）；200+HTML → json() 失败 → AiInvalidResponse；
- Feed 预览（feed_preview.py）：200+HTML → NotAFeedError；
- errors.py 把上述异常统一映射为 JSONResponse 信封（FastAPI 默认
  media_type application/json）。

本文件的测试即 BASELINE_OK 的验证性证据：FreshRSS 返回 HTML 错误页
（200）时，GET /api/v1/entries 必须得到 502 + application/json 信封，
响应体不含任何 HTML 标记；API 源 preview 端点同型验证。全部为
运行期伪造端点/凭据，无真实秘密。
"""

import secrets as _secrets

import httpx

from lumirss.adapters.freshrss import FreshRSSAdapter
from lumirss.config import FreshRSSSettings
from lumirss.main import app

FAKE_SECRET = "fake-test-" + _secrets.token_urlsafe(8)
FAKE_TOKEN = "fake-test-token-fix362"
BASE_URL = "http://freshrss-test.local"

_HTML_ERROR_PAGE = (
    "<!doctype html><html><head><title>502 Bad Gateway</title></head>"
    "<body><h1>502 Bad Gateway</h1><p>nginx/1.24.0</p></body></html>"
)


def _html_upstream_handler(request: httpx.Request) -> httpx.Response:
    """登录/token 正常放行，业务端点一律 200 + 反代风格 HTML 错误页
    （最隐蔽的失败形态：状态码说谎，正文不是 JSON）。"""
    if request.url.path.endswith("accounts/ClientLogin"):
        return httpx.Response(
            200, text=f"SID=unused\nLSID=unused\nAuth={FAKE_TOKEN}\n"
        )
    return httpx.Response(
        200,
        headers={"content-type": "text/html; charset=utf-8"},
        text=_HTML_ERROR_PAGE,
    )


def _html_upstream_adapter() -> FreshRSSAdapter:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_html_upstream_handler), trust_env=False
    )
    settings = FreshRSSSettings(
        _env_file=None,
        FRESHRSS_BASE_URL=BASE_URL,
        FRESHRSS_USERNAME="test-user",
        FRESHRSS_API_PASSWORD=FAKE_SECRET,
    )
    return FreshRSSAdapter(client, settings)


def test_freshrss_html_error_page_becomes_stable_json_envelope(client):
    """上游 HTML 错误页 → BFF 稳定 JSON 错误（正确 Content-Type）。

    前端拿到的必须是可以 .json() 的信封——绝不是 200 + HTML（会被
    解析成假成功），也不是 text/html 包装的 JSON。"""
    try:
        app.state.freshrss_adapter = _html_upstream_adapter()
        response = client.get("/api/v1/entries")
    finally:
        app.state.freshrss_adapter = None

    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()  # 前端解析不炸——这就是本修复的验收口径
    assert body["error"]["type"] == "upstream_error"
    # 上游 HTML 正文一个字节都不透传。
    assert "<html" not in response.text
    assert "nginx" not in response.text
    assert "Bad Gateway" not in response.text


def test_api_source_html_error_page_becomes_stable_json_envelope(
    client, monkeypatch
):
    """API 源 preview 端点同型验证：上游 200+HTML → 稳定 JSON 错误。

    fetch_json 在读体之前就检查 content-type（2MB 上限读不启动）；
    这里打真实路由层，仅把 pinned transport/SSRF 校验换成确定性桩。"""
    from lumirss import api_sources

    real_client = httpx.AsyncClient(
        transport=httpx.MockTransport(_html_upstream_handler), trust_env=False
    )

    class _PinnedStub:
        def build_request(self, *args, **kwargs):
            return real_client.build_request(*args, **kwargs)

        async def send(self, *args, **kwargs):
            return await real_client.send(*args, **kwargs)

        async def aclose(self):
            await real_client.aclose()

    async def _allow(_endpoint):
        return None

    monkeypatch.setattr(api_sources, "_pinned_client", lambda: _PinnedStub())
    monkeypatch.setattr(api_sources, "validate_hop", _allow)

    response = client.post(
        "/api/v1/api-sources/preview",
        json={
            "endpoint": "https://api.example.com/data.json",
            "itemsExpr": "items",
            "fieldMap": {"id": "id", "title": "title"},
        },
    )

    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["error"]["type"] == "fetch_failed"
    assert "<html" not in response.text
    assert "Bad Gateway" not in response.text
