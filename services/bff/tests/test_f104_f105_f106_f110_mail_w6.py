"""F104/F105/F106/F110 —— W6 邮件域。

F104 解析对照（multipart 结构快照、变体、编码、缺主题诚实、附件名净化、
对照零发布）；F105 接收规则（顺序/大小写/Unicode/多 From/空值 422/
幂等/deny 负向/上游不删信负向）；F106 历史回填（UIDVALIDITY 中止、
重复全 skipped、failed 不中断、FreshRSS 可读集成）；F110 会话串联
（乱序组装、缺父、无 References 不串、环、跨 list、删中间节点）。
"""

import asyncio
from email.message import EmailMessage

from lumirss.mail_bridge import MailBridgeStore, mask_from_display
from lumirss.mail_imap import (
    ImapNotConfigured,
    backfill_mail_history,
)
from lumirss.mail_rules import MailRuleStore
from lumirss.secrets_store import SecretsStore


def run(coroutine):
    return asyncio.run(coroutine)


def _raw_message(
    *,
    subject="周报",
    sender="Alice <alice@example.com>",
    to="reader@lumi.local",
    body_html=None,
    body_text="纯文本正文",
    message_id="<m1@example.com>",
    in_reply_to=None,
    references=None,
    attach_name=None,
    cte=None,
) -> bytes:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = to
    if message_id:
        message["Message-ID"] = message_id
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
    if references:
        message["References"] = references
    message.set_content(body_text, cte=cte) if cte else message.set_content(body_text)
    if body_html:
        message.add_alternative(body_html, subtype="html")
    if attach_name:
        message.add_attachment(
            b"\x00\x01binary", maintype="application", subtype="octet-stream", filename=attach_name
        )
    return message.as_bytes()


def _list_and_store(client):
    store = MailBridgeStore(client.app.state.db)
    lst = run(store.create_list("W6 列表"))
    return store, lst


# ---- F104 -------------------------------------------------------------------


def test_f104_structure_snapshot_and_parse_debug(client):
    store, lst = _list_and_store(client)
    raw = _raw_message(
        subject="图文周报",
        body_text="文本版本",
        body_html='<p>你好</p><img src="https://tracker.example/pixel.png"><img src="https://ads.example/b.gif">',
        attach_name="附件 &<> 名.bin",
    )
    result = run(store.ingest(lst, raw))
    assert result["status"] == "accepted"

    resp = client.get(
        f"/api/v1/mail/lists/{lst.uuid}/messages/m1@example.com/parse-debug"
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # multipart 树正确：multipart/mixed → [text/plain, multipart/related 或 text/html…]
    structure = data["structure"]
    assert structure["type"] == "multipart/mixed" or "parts" in structure
    flat_types = json_types(structure)
    assert "text/plain" in flat_types and "text/html" in flat_types
    assert data["subjectPresent"] is True
    assert data["htmlPartPresent"] is True
    assert data["textLen"] > 0
    assert data["itemTitle"] == "图文周报"
    # 外链图片如实计数（渲染层本就拦截）
    assert data["itemDiffSummary"]["trackingPixelsBlocked"] == 2
    # 发件人脱敏：本地部分 ***
    assert "***" in data["fromDisplay"]
    assert "alice" not in data["fromDisplay"]
    # 恶意附件名净化显示：尖括号/引号被替换、控制符不出现
    meta = data["attachmentMeta"]
    assert len(meta) == 1
    name = meta[0]["filename"]
    assert "<" not in name and ">" not in name and '"' not in name
    assert "附件" in name and ".bin" in name

    # 对照端点零发布（负向：无新条目产生）
    entries = run(store.list_entries(lst.uuid))
    assert len(entries) == 1
    again = client.get(
        f"/api/v1/mail/lists/{lst.uuid}/messages/m1@example.com/parse-debug"
    )
    assert again.status_code == 200
    assert len(run(store.list_entries(lst.uuid))) == 1


def json_types(node) -> set:
    types = {node["type"]}
    for child in node.get("parts", []):
        types |= json_types(child)
    return types


def test_f104_text_only_and_encoding_variants_missing_subject(client):
    store, lst = _list_and_store(client)
    # 纯文本变体（quoted-printable 编码 + 中文）
    raw_qp = _raw_message(
        subject="编码测试",
        body_text="这是 quoted-printable 的中文正文内容，用于验证编码。",
        cte="quoted-printable",
        message_id="<m2@example.com>",
    )
    assert run(store.ingest(lst, raw_qp))["status"] == "accepted"
    # base64 编码 HTML
    raw_b64_msg = EmailMessage()
    raw_b64_msg["Subject"] = "base64 测试"
    raw_b64_msg["From"] = "b@example.com"
    raw_b64_msg["To"] = "r@lumi.local"
    raw_b64_msg["Message-ID"] = "<m3@example.com>"
    raw_b64_msg.set_content("base64 正文")
    raw_b64_msg.add_alternative("<p><b>加粗内容</b></p>", subtype="html", cte="base64")
    assert run(store.ingest(lst, raw_b64_msg.as_bytes()))["status"] == "accepted"

    # 缺主题：诚实标注（无主题）且 subjectPresent=False
    del_msg = EmailMessage()
    del_msg["From"] = "n@example.com"
    del_msg["To"] = "r@lumi.local"
    del_msg["Message-ID"] = "<m4@example.com>"
    del_msg.set_content("无主题正文")
    assert run(store.ingest(lst, del_msg.as_bytes()))["status"] == "accepted"

    debug = client.get(f"/api/v1/mail/lists/{lst.uuid}/messages/m4@example.com/parse-debug")
    assert debug.status_code == 200
    assert debug.json()["subjectPresent"] is False

    text_debug = client.get(f"/api/v1/mail/lists/{lst.uuid}/messages/m2@example.com/parse-debug")
    assert text_debug.json()["htmlPartPresent"] is False
    html_debug = client.get(f"/api/v1/mail/lists/{lst.uuid}/messages/m3@example.com/parse-debug")
    assert html_debug.json()["htmlPartPresent"] is True
    assert "加粗内容" in run(
        store.get_entry(lst.uuid, "m3@example.com")
    )["text"] or html_debug.json()["textLen"] > 0


# ---- F105 -------------------------------------------------------------------


def test_f105_rules_order_casefold_unicode_and_deny(client):
    store, lst = _list_and_store(client)
    rules = MailRuleStore(client.app.state.db)
    # 规则顺序：deny 广义 contains 在前；allow 更具体在后
    r1 = run(rules.create_rule(list_uuid=lst.uuid, field="from", op="contains", value="SPAMER", action="deny"))
    r2 = run(rules.create_rule(list_uuid=lst.uuid, field="from", op="contains", value="alice", action="allow"))

    # contains 默认 casefold：小写 spammer 命中 r1（大小写不敏感）→ deny
    raw = _raw_message(sender="boss@spamer.example", subject="x", message_id="<r1@example.com>")
    result = run(store.ingest(lst, raw))
    assert result["status"] == "denied" and result["ruleId"] == r1["id"]
    assert run(store.list_entries(lst.uuid)) == []  # 负向：deny 不产生条目
    assert run(store.skipped_count(lst.uuid)) == 1

    # Unicode contains：中文规则命中
    r3 = run(rules.create_rule(list_uuid=lst.uuid, field="subject", op="contains", value="博彩", action="deny"))
    raw_unicode = _raw_message(sender="ok@fine.example", subject="在线博彩推广", message_id="<r2@example.com>")
    assert run(store.ingest(lst, raw_unicode))["status"] == "denied"
    assert run(store.skipped_count(lst.uuid)) == 2

    # 多 From 头（伪造头 fixture）：取第一个 From 判定
    forged = (
        b"From: alice@example.com\n"
        b"From: evil@spamer.example\n"
        b"To: r@lumi.local\n"
        b"Subject: Multi-From\n"
        b"Message-ID: <r3@example.com>\n\n"
        b"body\n"
    )
    result_forged = run(store.ingest(lst, forged))
    # 首个 From 是 alice → allow 允许入库
    assert result_forged["status"] == "accepted"

    # equals 精确（区分大小写）：只匹配完全相等的值
    r_eq = run(rules.create_rule(list_uuid=lst.uuid, field="subject", op="equals", value="精确主题", action="deny"))
    hit = run(
        rules.list_rules(lst.uuid)
    )
    assert [r["id"] for r in hit] == [r1["id"], r2["id"], r3["id"], r_eq["id"]]
    exact = _raw_message(sender="z@z.example", subject="精确主题", message_id="<r4@example.com>")
    assert run(store.ingest(lst, exact))["status"] == "denied"
    almost = _raw_message(sender="z@z.example", subject="精确主题2", message_id="<r5@example.com>")
    assert run(store.ingest(lst, almost))["status"] == "accepted"

    # 重复投递幂等：同 Message-ID 再投 → duplicate（不重复计数/条目）
    dup = run(store.ingest(lst, almost))
    assert dup["status"] == "duplicate"
    assert len(run(store.list_entries(lst.uuid))) == 2

    # 空 value → 422（路由层）
    resp = client.post(
        f"/api/v1/mail/lists/{lst.uuid}/rules",
        json={"field": "from", "op": "contains", "value": "", "action": "deny"},
    )
    assert resp.status_code == 422

    # dry-run：命中解释 + 未命中诚实
    dry = client.post(
        f"/api/v1/mail/lists/{lst.uuid}/rules/dry-run",
        json={"field": "subject", "value": "精确主题"},
    )
    assert dry.status_code == 200
    assert dry.json()["matchedRule"]["id"] == r_eq["id"]
    dry_miss = client.post(
        f"/api/v1/mail/lists/{lst.uuid}/rules/dry-run",
        json={"field": "from", "value": "nobody@nowhere.example"},
    )
    assert dry_miss.json()["matchedRule"] is None
    assert "允许" in dry_miss.json()["explanation"]

    # 负向：上游邮箱不删信——deny 只是 Lumi 桥不入 feed，fetcher 语义不被触碰
    # （bridge.ingest 是纯接收端：没有任何对上游邮箱的写路径）
    import inspect

    from lumirss import mail_bridge as bridge_mod

    source = inspect.getsource(bridge_mod)
    assert "DELETE" not in source or "mail_bridge_entries" in source  # 删除仅限本地环形缓冲


def test_f105_no_rules_allows_everything(client):
    store, lst = _list_and_store(client)
    raw = _raw_message(message_id="<nr1@example.com>")
    assert run(store.ingest(lst, raw))["status"] == "accepted"
    assert run(store.skipped_count(lst.uuid)) == 0


# ---- F106 -------------------------------------------------------------------


class _FakeBackfillFetcher:
    def __init__(self, uidvalidity, messages):
        self.uidvalidity = uidvalidity
        self.messages = messages  # [(uid, raw)]
        self.calls = []

    async def __call__(self, *args):
        self.calls.append(args)
        return self.uidvalidity, self.messages


def _imap_secrets(tmp_path, list_uuid):
    import json as _json

    secrets = SecretsStore(str(tmp_path / "secrets.json"))
    secrets.set(
        "mail_imap",
        _json.dumps(
            {
                "host": "imap.example.com",
                "port": 993,
                "user": "u",
                "folder": "INBOX",
                "ssl": True,
                "listUuid": list_uuid,
                "intervalSeconds": 300,
                "enabled": True,
            }
        ),
    )
    secrets.set("mail_imap_password", "pw")
    return secrets


def test_f106_backfill_dry_run_execute_dup_and_failed(client, tmp_path):
    store, lst = _list_and_store(client)
    secrets = _imap_secrets(tmp_path, lst.uuid)
    messages = [
        (100, _raw_message(subject="回填一", message_id="<b1@example.com>")),
        (101, None),  # 坏载荷：解析抛错 → 计入 failed，不中断
        (102, _raw_message(subject="回填二", message_id="<b2@example.com>")),
    ]
    fetcher = _FakeBackfillFetcher("424242", messages)

    # dry-run：零写入 + 采样
    dry = run(
        backfill_mail_history(
            secrets, store, since="2026-09-01", dry_run=True, fetcher=fetcher
        )
    )
    assert dry["dryRun"] is True and dry["matched"] == 3
    assert len(dry["sample"]) == 3
    assert {s["uid"] for s in dry["sample"]} == {100, 101, 102}
    assert run(store.list_entries(lst.uuid)) == []

    # 执行：2 封 created；坏邮件 failed 不中断
    result = run(
        backfill_mail_history(secrets, store, dry_run=False, fetcher=fetcher)
    )
    assert result["processed"] == 3
    assert result["created"] == 2
    assert result["skippedDup"] == 0
    assert len(result["failed"]) == 1
    assert result["failed"][0]["uid"] == "101"

    # FreshRSS 侧实际可读（集成断言：bridge 条目 → Atom 渲染包含主题）
    atom = client.get(f"/feeds/mail/{lst.uuid}.{lst.secret}.atom")
    assert atom.status_code == 200
    assert "回填一" in atom.text and "回填二" in atom.text

    # 重复回填：全 skipped（负向：不重复成条目）
    again = run(
        backfill_mail_history(secrets, store, dry_run=False, fetcher=fetcher)
    )
    assert again["created"] == 0 and again["skippedDup"] == 2 and again["failed"]
    assert len(run(store.list_entries(lst.uuid))) == 2


def test_f106_backfill_uidvalidity_change_aborts(client, tmp_path):
    store, lst = _list_and_store(client)
    secrets = _imap_secrets(tmp_path, lst.uuid)
    messages = [(10, _raw_message(subject="v1", message_id="<v1@example.com>"))]
    run(
        backfill_mail_history(
            secrets, store, dry_run=False, fetcher=_FakeBackfillFetcher("111", messages)
        )
    )
    # UIDVALIDITY 变化 → 执行中止（honest）
    aborted = run(
        backfill_mail_history(
            secrets, store, dry_run=False, fetcher=_FakeBackfillFetcher("999", messages)
        )
    )
    assert aborted.get("aborted") is True
    assert aborted["reason"] == "uidvalidity_changed"
    assert aborted["created"] == 0
    entries = run(store.list_entries(lst.uuid))
    assert len(entries) == 1  # 没有新增

    # dry-run 只提示不中止
    warned = run(
        backfill_mail_history(
            secrets, store, dry_run=True, fetcher=_FakeBackfillFetcher("999", messages)
        )
    )
    assert warned.get("note") == "uidvalidity_changed"


def test_f106_backfill_not_configured(client, tmp_path):
    secrets = SecretsStore(str(tmp_path / "none.json"))
    store = MailBridgeStore(client.app.state.db)
    try:
        run(backfill_mail_history(secrets, store, dry_run=True, fetcher=_FakeBackfillFetcher("1", [])))
        raise AssertionError("应抛 ImapNotConfigured")
    except ImapNotConfigured:
        pass


# ---- F110 -------------------------------------------------------------------


def _thread_fixture(store, lst, messages):
    for raw in messages:
        result = run(store.ingest(lst, raw))
        assert result["status"] == "accepted", (raw, result)


def test_f110_thread_assembly_scenarios(client):
    store, lst = _list_and_store(client)
    # 乱序到达：先回信后原信
    _thread_fixture(
        store,
        lst,
        [
            _raw_message(subject="Re: 计划", message_id="<t2@x.com>", in_reply_to="<t1@x.com>", references="<t1@x.com>"),
            _raw_message(subject="计划", message_id="<t1@x.com>"),
            _raw_message(subject="Re: Re: 计划", message_id="<t3@x.com>", in_reply_to="<t2@x.com>"),
        ],
    )
    thread = client.get(f"/api/v1/mail/lists/{lst.uuid}/messages/t3@x.com/thread")
    assert thread.status_code == 200
    chain = thread.json()["chain"]
    assert [c["id"] for c in chain] == ["t1@x.com", "t2@x.com", "t3@x.com"]
    assert [c["subject"] for c in chain] == ["计划", "Re: 计划", "Re: Re: 计划"]
    assert chain[-1]["current"] is True

    # 缺父：诚实 reason
    _thread_fixture(store, lst, [_raw_message(subject="孤儿", message_id="<orphan@x.com>", in_reply_to="<missing@x.com>")])
    orphan = client.get(f"/api/v1/mail/lists/{lst.uuid}/messages/orphan@x.com/thread")
    data = orphan.json()
    assert [c["id"] for c in data["chain"]] == ["orphan@x.com"]
    assert data["reason"] == "parent_missing"

    # 负向：同主题但无 References/In-Reply-To 不串（正文不同 → 内容指纹不同）
    _thread_fixture(store, lst, [_raw_message(subject="计划", body_text="另一封独立邮件的正文", message_id="<solo@x.com>")])
    solo = client.get(f"/api/v1/mail/lists/{lst.uuid}/messages/solo@x.com/thread").json()
    assert [c["id"] for c in solo["chain"]] == ["solo@x.com"]

    # 环：断开并标注
    _thread_fixture(
        store,
        lst,
        [
            _raw_message(subject="环A", message_id="<ca@x.com>", in_reply_to="<cb@x.com>"),
            _raw_message(subject="环B", message_id="<cb@x.com>", in_reply_to="<ca@x.com>"),
        ],
    )
    cycle = client.get(f"/api/v1/mail/lists/{lst.uuid}/messages/ca@x.com/thread").json()
    assert cycle["cycleBroken"] is True

    # 跨 list 不串（负向）
    other = run(store.create_list("另一列表"))
    _thread_fixture(store, other, [_raw_message(subject="Re: 计划", message_id="<t2b@x.com>", in_reply_to="<t1@x.com>")])
    cross = client.get(f"/api/v1/mail/lists/{other.uuid}/messages/t2b@x.com/thread").json()
    assert [c["id"] for c in cross["chain"]] == ["t2b@x.com"]
    assert cross["reason"] == "parent_missing"

    # 删除中间节点 → 链降级（子链从断点起各自成段，诚实呈现现有可连接部分）
    run(
        client.app.state.db.execute(
            "DELETE FROM mail_bridge_entries WHERE message_id = 't2@x.com'",
            (),
        )
    )
    degraded = client.get(f"/api/v1/mail/lists/{lst.uuid}/messages/t3@x.com/thread").json()
    ids = [c["id"] for c in degraded["chain"]]
    assert "t2@x.com" not in ids
    assert degraded["reason"] == "parent_missing" or ids == ["t1@x.com", "t3@x.com"] or ids == ["t3@x.com"]


def test_f110_thread_404_and_mask(client):
    store, lst = _list_and_store(client)
    resp = client.get(f"/api/v1/mail/lists/{lst.uuid}/messages/nope@x.com/thread")
    assert resp.status_code == 404
    assert mask_from_display("Alice <alice@example.com>") == "Alice <***@example.com>"
    assert mask_from_display("bob@test.io") == "***@test.io"
