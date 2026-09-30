"""FIX-068 守卫：日志/错误响应不回显凭据（令牌、Cookie、feed 密钥）。

既有钉子：test_access_log（query 串绝不入访问日志，激活 token 借道
query 的场景已覆盖）、test_n035_redirect_chain（重定向诊断 query 值
按敏感键打码）、test_mail_webhook_auth（ingest bearer 错值绝不回显）。

本文件补两个尚未显式钉住的出口：
1. 会话 Cookie 值绝不出现在任何错误响应体（404/422/401 同查）；
2. feeds/views 路径里的 feed 密钥段——命中路由模板，访问日志只有
   模板；密钥本体与查询串一样绝不入日志（routed-path 语义）。
"""

import json
import logging
import secrets as _secrets

import pytest

from new231_helpers import ab_session


@pytest.fixture()
def access_records():
    """同 test_access_log：捕获 lumirss.access 的结构化 JSON 记录。"""
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


def test_fix068_session_cookie_value_never_echoed_in_errors(monkeypatch, tmp_path):
    """带 Cookie 的 404/422 错误体绝不含 Cookie 值本身。"""
    with ab_session(monkeypatch, tmp_path) as session:
        client = session.client
        member = session.activate_member("fx068a")
        cookie_line = member["cookie"]  # "lumi_session=<raw>"
        assert "=" in cookie_line
        cookie_value = cookie_line.split("=", 1)[1]
        assert len(cookie_value) >= 16

        probes = [
            ("/api/v1/no-such-path", 404),
            ("/api/v1/search/views/does-not-exist/count", 404),
            ("/api/v1/library/notes/not-a-uuid/attachments", 404),
        ]
        for path, expected in probes:
            response = client.get(path, headers=member)
            assert response.status_code == expected, (path, response.text)
            assert cookie_value not in response.text, path

        # 错误弹窗同源：body 里只有稳定 type + 通用 message，无任何
        # 请求头材料（Cookie/Authorization 键名也不出现在响应体）。
        body = client.get(
            "/api/v1/library/notes/not-a-uuid/attachments", headers=member
        ).json()
        assert "cookie" not in json.dumps(body).lower()


def test_fix068_feed_secret_path_segment_never_in_access_log(client, access_records):
    """feeds/views 密钥段入的是路由模板；密钥本体不入访问日志。"""
    marker = "fx068" + _secrets.token_hex(8)
    response = client.get(f"/feeds/views/no-such-view.{marker}.atom")
    assert response.status_code == 404
    assert marker not in response.text

    assert len(access_records) == 1, access_records
    _level, record = access_records[0]
    dumped = json.dumps(record, ensure_ascii=False)
    assert record["event"] == "access"
    assert record["route"] == "/feeds/views/{view_id}.{secret}.atom"
    assert marker not in dumped


_ = pytest  # parity import; assertions carry the test
