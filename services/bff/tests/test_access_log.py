"""E01 结构化访问日志 — 字段契约与脱敏边界。

每个请求在 lumirss.access 恰好一条 JSON 记录：request_id / method /
route 模板 / status / duration_ms / 服务端派生 actor / 异常类名。
绝不出现：query string（激活 token 借道于此）、请求体、凭据。
LUMIRSS_ACCESS_LOG=off 时完全静默。"""

import json
import logging

import pytest


@pytest.fixture()
def access_records():
    records: list[tuple[int, dict]] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append((record.levelno, json.loads(record.getMessage())))

    handler = _Capture()
    logger = logging.getLogger("lumirss.access")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield records
    finally:
        logger.removeHandler(handler)


def _single(records):
    assert len(records) == 1, records
    return records[0]


def test_access_log_fields_on_routed_request(client, access_records):
    response = client.get("/api/v1/version")
    assert response.status_code == 200
    level, record = _single(access_records)
    assert record["event"] == "access"
    assert record["component"] == "http"
    assert record["request_id"] == response.headers["x-request-id"]
    assert record["method"] == "GET"
    # 命中路由 → 记录模板而非具体路径
    assert record["route"] == "/api/v1/version"
    assert record["status"] == 200
    assert isinstance(record["duration_ms"], int)
    assert record["error"] is None
    assert level == logging.INFO


def test_access_log_never_contains_query_string(client, access_records):
    # 激活预览的 token 走 query string —— 日志只允许路径本身。
    response = client.get(
        "/api/v1/auth/activation-preview?token=super-secret-token-value"
    )
    assert response.status_code in (200, 400, 404)
    _, record = _single(access_records)
    assert "super-secret-token-value" not in json.dumps(record)


def test_access_log_warning_level_for_client_error(client, access_records):
    response = client.get("/api/v1/search", params={"q": "   "})
    assert response.status_code == 400
    level, record = _single(access_records)
    assert record["status"] == 400
    assert level == logging.WARNING


def test_access_log_off_silences(client, monkeypatch, access_records):
    monkeypatch.setenv("LUMIRSS_ACCESS_LOG", "off")
    response = client.get("/api/v1/version")
    assert response.status_code == 200
    assert access_records == []
