"""FIX-369 基线验证：公共探活端点不泄露异常堆栈、内部地址或数据库路径。

/health/live 只回 ``{"status": "ok"}``；/health/ready 的组件错误永远只带
稳定 ``type``（errors.py/operations.py 的既有红线："only type ever leaves
the BFF"），不透出 FreshRSS/RSSHub 内部主机名、sqlite 路径或异常文本。
本文件把这条红线钉成回归测试（BASELINE_OK——无需修复，验证既有行为）。
"""

import pytest
from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.storage import Database

# 公共探活面上不允许出现的内部信息痕迹：文件系统路径、URL、堆栈关键字。
_LEAK_MARKERS = (
    "/data/",
    ".sqlite",
    "File \"",
    "Traceback",
    "http://freshrss",
    "http://rsshub",
    "greader.php",
)


def _assert_no_internal_detail(payload: object) -> None:
    import json

    text = json.dumps(payload, ensure_ascii=False)
    for marker in _LEAK_MARKERS:
        assert marker not in text, f"public probe leaked {marker!r}: {text}"


def test_health_live_payload_is_exactly_status_ok():
    with TestClient(app) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_ready_healthy_payload_is_status_only():
    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    _assert_no_internal_detail(payload)
    # freshrss/rsshub 只透出状态字符串，不带主机名/URL/错误文本。
    assert isinstance(payload["components"]["freshrss"], str)
    assert isinstance(payload["components"]["rsshub"], str)


def test_health_ready_degraded_payload_carries_only_error_type(tmp_path):
    """sqlite 不可用时：503 + status 布尔语义不变；error 只有 type，
    永远没有异常消息、数据库路径或堆栈。"""
    with TestClient(app) as client:
        ro = tmp_path / "ro"
        ro.mkdir()
        ro.chmod(0o500)
        previous = app.state.db
        app.state.db = Database(str(ro / "lumi.sqlite"))
        try:
            response = client.get("/health/ready")
        finally:
            app.state.db = previous
            ro.chmod(0o700)
    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "unavailable"
    _assert_no_internal_detail(payload)
    assert payload["components"]["sqlite"]["status"] == "unavailable"
    assert payload["components"]["sqlite"]["error"] == {"type": "database_error"}


def test_version_endpoint_stays_minimal():
    """构建溯源只暴露 version/commit/apiVersion——无环境转储、无路径。"""
    with TestClient(app) as client:
        response = client.get("/api/v1/version")
    assert response.status_code == 200
    assert set(response.json().keys()) == {"version", "commit", "apiVersion"}


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/operations/status",
        "/api/v1/operations/diagnostics",
    ],
)
def test_detailed_diagnostics_require_session(path, monkeypatch):
    """详细诊断仅限授权入口：/api/* 在 session 模式下无 cookie 一律 401，
    详细状态（full_status，含组件延迟/错误详情）不走公共探活面。"""
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    with TestClient(app) as client:
        response = client.get(path)
    assert response.status_code == 401


def test_ready_anonymous_binds_owner_context_session_mode(monkeypatch):
    """R01 回归：session 多账户模式下 /health/ready 匿名可探且 200。

    basic 单用户模式里匿名请求隐式携带 owner 上下文；切到 session 后
    匿名请求没有用户身份，RoutingDatabase._connect 会拒绝——就绪探针
    是 CLI 健康门/编排器的匿名入口，必须显式绑定 owner 上下文（与
    后台扫描循环同一模式），探针语义与请求身份解耦。
    """
    import lumirss.routers.health as health_module
    from lumirss.operations import OperationsService
    from lumirss.user_scope import current_user_id

    seen: dict[str, object] = {}

    class _ProbeService:
        async def ready(self) -> tuple[bool, dict]:
            seen["user_id"] = current_user_id()
            return True, {"status": "ok", "components": {}}

    assert not isinstance(OperationsService, type(None))  # 保持导入语义清晰
    app.state.owner_id = "u-owner"
    monkeypatch.setattr(
        health_module, "_get_operations_service", lambda request: _ProbeService()
    )
    try:
        with TestClient(app) as probe:
            response = probe.get("/health/ready")
    finally:
        app.state.owner_id = None
    assert response.status_code == 200
    # 绑定的是启动时解析的真实 owner（非请求者身份）
    assert seen["user_id"] == app.state.owner_id
    assert seen["user_id"]
    assert response.json()["error"]["type"] == "session_required"
    assert response.headers.get("cache-control") == "no-store"
