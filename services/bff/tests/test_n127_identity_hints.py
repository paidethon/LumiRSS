"""N127 邮件来源身份提示 — ingest 时服务端计算的 From/Reply-To 线索。

不一致（Reply-To 域不同 / 显示名里的域名与实际邮箱域不同）→ 落
identity_hints_json 并在 detail 中返回；一致 → 无提示（诚实：没有就
是 null）。UI 文案是中性的「提示」+ 明确「客户端不验证 SPF/DKIM，
无法确认真实性」（web 侧测试断言）——绝无反欺骗断言。
"""

from lumirss.mail_bridge import _identity_hints


def _mail(from_header: str, reply_to: str | None = None, mid="n127@example.com"):
    headers = (
        f"From: {from_header}\r\n"
        "To: reader@example.com\r\nSubject: 身份提示\r\n"
        f"Message-ID: <{mid}>\r\nMIME-Version: 1.0\r\n"
    )
    if reply_to:
        headers += f"Reply-To: {reply_to}\r\n"
    return (
        headers
        + "Content-Type: text/html; charset=utf-8\r\n\r\n<p>正文</p>\r\n"
    ).encode()


def _bridge_and_ingest(client, raw: bytes, name="身份提示列表"):
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


def _detail(client, lst, message_id):
    response = client.get(
        f"/api/v1/mail/lists/{lst['uuid']}/messages/{message_id}/detail"
    )
    assert response.status_code == 200
    return response.json()


def test_reply_to_mismatch_flagged(client):
    lst, message_id = _bridge_and_ingest(
        client,
        _mail(
            "Newsletter <news@weekly.example>",
            "Reply-To: different@example.net",
            mid="n127-rt@example.com",
        ),
        "回复不一致",
    )
    detail = _detail(client, lst, message_id)
    hints = detail["identityHints"]
    assert hints is not None
    assert hints["replyToMismatch"] is True
    assert hints["replyToAddress"] == "different@example.net"
    assert hints["fromAddress"] == "news@weekly.example"


def test_display_name_domain_mismatch_flagged(client):
    lst, message_id = _bridge_and_ingest(
        client,
        _mail(
            '"PayPal - paypal.com 客服" <alert@paypa1-echo.example>',
            mid="n127-dn@example.com",
        ),
        "显示名不一致",
    )
    hints = _detail(client, lst, message_id)["identityHints"]
    assert hints is not None
    assert hints["displayNameDomainMismatch"] is True
    assert "paypal.com" in hints["displayNameDomains"]


def test_matching_sender_produces_no_hint(client):
    lst, message_id = _bridge_and_ingest(
        client,
        _mail(
            "每周精选 <news@weekly.example>",
            "Reply-To: news@weekly.example",
            mid="n127-ok@example.com",
        ),
        "一致无提示",
    )
    detail = _detail(client, lst, message_id)
    assert detail["identityHints"] is None
    listing = client.get(f"/api/v1/mail/lists/{lst['uuid']}/messages").json()
    assert listing["items"][0]["hasIdentityHints"] is False


def test_reply_to_same_domain_not_flagged(client):
    lst, message_id = _bridge_and_ingest(
        client,
        _mail(
            "Newsletter <news@weekly.example>",
            "Reply-To: bounce@weekly.example",
            mid="n127-same@example.com",
        ),
        "同域回复",
    )
    hints = _detail(client, lst, message_id)["identityHints"]
    assert hints is None


def test_identity_hints_unit_matrix():
    import email
    import email.policy

    def parse(raw: str):
        return email.message_from_string(raw, policy=email.policy.default)

    mismatch = _identity_hints(
        parse(
            "From: A <a@x.example>\r\nReply-To: b@y.example\r\n\r\nhi"
        )
    )
    assert mismatch is not None and mismatch["replyToMismatch"] is True
    match = _identity_hints(parse("From: A <a@x.example>\r\n\r\nhi"))
    assert match is None
    no_from = _identity_hints(parse("Subject: 无发件人\r\n\r\nhi"))
    assert no_from is None


def test_hints_stored_bounded_and_honest_content(client):
    """hints 只含头解析结果（地址/域名/旗标），没有任何验证声明字段。"""
    lst, message_id = _bridge_and_ingest(
        client,
        _mail(
            '"Win - win-big-prizes.cn 中奖" <claim@stranger.example>',
            mid="n127-honest@example.com",
        ),
        "诚实文案",
    )
    hints = _detail(client, lst, message_id)["identityHints"]
    assert hints is not None
    assert "spf" not in str(hints).lower()
    assert "dkim" not in str(hints).lower()
    assert "verified" not in str(hints).lower()
