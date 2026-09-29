"""NEW-289 简报纯文本邮件文件 — RFC 5322 EML 导出（绝不发送）。"""

import email
import email.policy

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new281_helpers import confirm, create_issue, iso, seed


def _export(client, headers, issue_id):
    return client.get(f"/api/v1/briefings/{issue_id}/export.eml", headers=headers)


def test_export_confirmed_eml(ab_env):  # noqa: F811
    """确认期次 → message/rfc822 附件；头部与正文如实携带编辑来源。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    manual = seed(env, "a", title="人工选入的文章", published=iso(hours=-5))
    rule = seed(env, "a", title="规则推荐的文章", published=iso(hours=-4))
    issue_id = client.post(
        "/api/v1/briefings",
        json={
            "title": "导出的一期",
            "rangeFrom": iso(days=-2),
            "rangeTo": iso(hours=-1),
            "sections": [{"key": "main", "label": "要闻"}],
            "items": [
                {"entryRef": manual["entryRef"], "sectionKey": "main",
                 "title": manual["title"], "url": "https://example.com/a"},
                {"entryRef": rule["entryRef"], "sectionKey": "main",
                 "title": rule["title"], "provenance": "rule"},
            ],
        },
        headers=a,
    ).json()["id"]
    confirm(client, a, issue_id)

    response = _export(client, a, issue_id)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("message/rfc822")
    assert "attachment" in response.headers.get("content-disposition", "")
    assert ".eml" in response.headers.get("content-disposition", "")

    message = email.message_from_bytes(
        response.content, policy=email.policy.default
    )
    assert message["Subject"] == "导出的一期"
    assert message["From"] == "LumiRSS Briefing <briefing@lumirss.local>"
    assert message["Date"]
    assert message["Message-ID"] == f"<briefing-{issue_id}@lumirss.local>"
    text = message.get_body(preferencelist=("plain",)).get_content()
    assert "== 要闻 ==" in text
    assert "* [编辑选入] 人工选入的文章" in text
    assert "* [规则推荐] 规则推荐的文章" in text
    assert "链接：https://example.com/a" in text
    # HTML 替代部分同样存在（双部分结构）
    html = message.get_body(preferencelist=("html",))
    assert html is not None


def test_export_draft_and_unknown(ab_env):  # noqa: F811
    """草稿 → 409 briefing_not_confirmed；未知期次 → 404。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    card = seed(env, "a", title="草稿文章", published=iso(hours=-5))
    issue_id = create_issue(client, a, title="未确认", cards=[card]).json()["id"]
    draft = _export(client, a, issue_id)
    assert draft.status_code == 409
    assert draft.json()["error"]["type"] == "briefing_not_confirmed"
    assert _export(client, a, "no-such-issue").status_code == 404


def test_eml_includes_corrections(ab_env):  # noqa: F811
    """更正（290）追加进 EML：主题带计数、正文带更正与不替换声明。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    card = seed(env, "a", title="待更正", published=iso(hours=-5))
    issue_id = create_issue(client, a, title="有一处错误", cards=[card]).json()["id"]
    confirm(client, a, issue_id)
    correction = client.post(
        f"/api/v1/briefings/{issue_id}/corrections",
        json={"body": "第二段日期应为 9 月 28 日。"},
        headers=a,
    )
    assert correction.status_code == 201

    response = _export(client, a, issue_id)
    message = email.message_from_bytes(
        response.content, policy=email.policy.default
    )
    assert message["Subject"] == "有一处错误（更正 1 条）"
    text = message.get_body(preferencelist=("plain",)).get_content()
    assert "【更正" in text
    assert "9 月 28 日" in text
    assert "未做静默替换" in text


def test_eml_builder_has_no_smtp_path(ab_env):  # noqa: F811
    """导出模块零 SMTP：无 smtplib 导入、无任何发信调用（诚实硬边界）。"""
    import inspect

    import lumirss.new289_eml as eml_module

    source = inspect.getsource(eml_module)
    assert "import smtplib" not in source
    assert "from smtplib" not in source
    assert "SMTP(" not in source
    assert "send_message" not in source
    assert "sendmail" not in source


def test_cross_user_export_isolated(ab_env):  # noqa: F811
    """B 不能导出 A 的期次（404 同形）。"""
    env = ab_env
    client = env["client"]
    card = seed(env, "a", title="A 的私享", published=iso(hours=-5))
    issue_id = create_issue(client, env["a"], title="A 的一期", cards=[card]).json()["id"]
    confirm(client, env["a"], issue_id)
    assert _export(client, env["b"], issue_id).status_code == 404
