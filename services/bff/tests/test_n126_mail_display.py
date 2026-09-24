"""N126 邮件正文显示模式 — 文本/HTML 双形态 + 被阻止的外链媒体。

ingest 时记录被剥离的外链媒体 URL（有界 ≤20，去重保序）；detail 端点
同时提供 text（charset 诚实解码后的纯文本）与 html（净化产物）两个
形态；文本模式不乱码（utf-8 与 latin-1 回退 fixture）；HTML 模式渲染
只取净化产物，客户端切换不产生任何远程请求（web 侧测试覆盖）。
"""

import asyncio
import json

from lumirss.mail_sanitize import sanitize_email_html_with_blocked
from lumirss.main import app


def run(coro):
    return asyncio.run(coro)


def _mail(raw_html: str, text_part: str | None = None, mid="n126@example.com") -> bytes:
    body = (
        "From: Newsletter <news@example.com>\r\n"
        f"To: reader@example.com\r\nSubject: 显示模式\r\n"
        f"Message-ID: <{mid}>\r\nMIME-Version: 1.0\r\n"
    )
    if text_part is None:
        return (
            body
            + 'Content-Type: text/html; charset=utf-8\r\n\r\n'
            + raw_html
            + "\r\n"
        ).encode()

    return (
        body
        + 'Content-Type: multipart/alternative; boundary="MM"\r\n\r\n'
        + "--MM\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
        + text_part
        + "\r\n--MM\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        + raw_html
        + "\r\n--MM--\r\n"
    ).encode()


def _bridge_and_ingest(client, raw: bytes, name="显示模式列表"):
    created = client.post("/api/v1/mail/bridge-lists", json={"name": name})
    assert created.status_code == 201
    lst = created.json()
    ingested = client.post(
        f"/api/mail/ingest/{lst['uuid']}",
        content=raw,
        headers={"Authorization": f"Bearer {lst['secret']}"},
    )
    assert ingested.status_code == 200, ingested.text
    return lst, ingested.json()["messageId"]


def test_blocked_media_recorded_at_ingest(client):
    raw = _mail(
        "<p>正文开始</p>"
        '<img src="https://tracker.example/pixel.gif">'
        '<img src="https://tracker.example/pixel.gif">'
        '<img src="//cdn.example/banner.png">'
        '<img src="data:image/gif;base64,AAAA">'
        "<p>正文结束</p>"
    )
    lst, message_id = _bridge_and_ingest(client, raw)
    detail = client.get(
        f"/api/v1/mail/lists/{lst['uuid']}/messages/{message_id}/detail"
    ).json()
    blocked = detail["blockedMedia"]
    # 去重保序；data URI（内联）不算外链
    assert blocked == [
        "https://tracker.example/pixel.gif",
        "//cdn.example/banner.png",
    ]
    # 净化后的 HTML 不含任何 img（渲染面零远程加载）
    assert "<img" not in detail["html"]
    # 列表旗标同步
    listing = client.get(f"/api/v1/mail/lists/{lst['uuid']}/messages").json()
    assert listing["items"][0]["blockedMediaCount"] == 2


def test_blocked_media_bounded_at_20(client):
    imgs = "".join(
        f'<img src="https://t{i}.example/p.gif">' for i in range(30)
    )
    raw = _mail(f"<p>hi</p>{imgs}", mid="n126-bound@example.com")
    lst, message_id = _bridge_and_ingest(client, raw, "上限媒体")
    row = run(
        app.state.db.fetch_one(
            "SELECT blocked_media_json FROM mail_bridge_entries WHERE list_uuid = ? AND message_id = ?",
            (lst["uuid"], message_id),
        )
    )
    blocked = json.loads(str(row["blocked_media_json"]))
    assert len(blocked) == 20


def test_detail_serves_both_text_and_html_modes(client):
    raw = _mail(
        "<h1>HTML 标题</h1><p>HTML 正文</p>",
        text_part="纯文本标题\n纯文本正文",
        mid="n126-both@example.com",
    )
    lst, message_id = _bridge_and_ingest(client, raw, "双形态")
    detail = client.get(
        f"/api/v1/mail/lists/{lst['uuid']}/messages/{message_id}/detail"
    ).json()
    assert "纯文本正文" in detail["text"]
    assert "<h1>HTML 标题</h1>" in detail["html"]
    # html 是净化产物：无脚本
    assert "<script" not in detail["html"].lower()


def test_text_mode_charset_honest_no_mojibake(client):
    """utf-8 正文 + latin-1 回退：存储的 text 是按声明 charset 解码后的
    文本（email 模块职责），detail 原样回放，不二次乱码。"""
    import base64

    utf8_text = "每周精选：第 42 期（中文不乱码）"
    latin_text = "caf\xe9 cr\xe8me br\xfbl\xe9e"
    raw = (
        "From: Newsletter <news@example.com>\r\n"
        "To: reader@example.com\r\nSubject: 编码\r\n"
        "Message-ID: <n126-charset@example.com>\r\n"
        "MIME-Version: 1.0\r\n"
        'Content-Type: multipart/alternative; boundary="CE"\r\n\r\n'
        "--CE\r\nContent-Type: text/plain; charset=utf-8\r\n"
        "Content-Transfer-Encoding: base64\r\n\r\n"
        + base64.b64encode(utf8_text.encode()).decode()
        + "\r\n"
        + "--CE\r\nContent-Type: text/plain; charset=iso-8859-1\r\n\r\n"
        + latin_text
        + "\r\n--CE--\r\n"
    ).encode()
    lst, message_id = _bridge_and_ingest(client, raw, "编码")
    detail = client.get(
        f"/api/v1/mail/lists/{lst['uuid']}/messages/{message_id}/detail"
    ).json()
    assert utf8_text in detail["text"]
    detail_latin = detail["text"]
    assert "cafÃ©" not in detail_latin  # 无双重编码 mojibake


def test_mail_without_html_part_has_html_fallback(client):
    """纯文本邮件：html 列装的是文本兜底（既有语义不变），text 是原文。"""
    raw = (
        "From: Newsletter <news@example.com>\r\n"
        "To: reader@example.com\r\nSubject: 纯文本\r\n"
        "Message-ID: <n126-plain@example.com>\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        "只有纯文本的一封邮件\r\n"
    ).encode()
    lst, message_id = _bridge_and_ingest(client, raw, "纯文本")
    detail = client.get(
        f"/api/v1/mail/lists/{lst['uuid']}/messages/{message_id}/detail"
    ).json()
    assert "只有纯文本的一封邮件" in detail["text"]


def test_sanitize_records_media_and_keeps_safety_matrix():
    dirty = (
        "<h1>标题</h1>"
        '<img src="https://t.example/x.gif">'
        '<img src="https://t.example/x.gif">'
        '<video src="https://v.example/a.mp4"></video>'
        "<script>alert(1)</script>"
        "<p>正文</p>"
    )
    clean, blocked = sanitize_email_html_with_blocked(dirty)
    assert "<script" not in clean and "alert" not in clean
    assert "<img" not in clean and "<video" not in clean
    assert blocked == [
        "https://t.example/x.gif",
        "https://v.example/a.mp4",
    ]
    # 兼容包装：sanitize_email_html 仍只返回 HTML
    from lumirss.mail_sanitize import sanitize_email_html

    assert sanitize_email_html(dirty) == clean


def test_message_detail_404_unknown(client):
    lst, _mid = _bridge_and_ingest(client, _mail("<p>x</p>"), "未知详情")
    missing = client.get(
        f"/api/v1/mail/lists/{lst['uuid']}/messages/ghost@nowhere/detail"
    )
    assert missing.status_code == 404
    unknown_list = client.get(
        "/api/v1/mail/lists/no-such/messages/anything/detail"
    )
    assert unknown_list.status_code == 404
