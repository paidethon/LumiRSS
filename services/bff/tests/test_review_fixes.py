"""独立复审 P1 修复回归。

1. SmtpSendFailed 曾在插入时区辅助函数时被拆坏 —— str(exc) 退化成
   tuple repr，污染错误信封与 last_error。
2. 库腿 search_page 的 limit+1 hasMore 探测曾被内部 50 行 clamp 吞掉
   —— 页大小恰为 50 时 hasMore 说谎（旧 #11 失败类别）。
"""

import asyncio

from lumirss.mail_digest import SmtpSendFailed


def run(coroutine):
    return asyncio.run(coroutine)


def test_smtp_send_failed_str_is_the_message():
    exc = SmtpSendFailed("SMTP 认证失败。", "auth_failed")
    assert str(exc) == "SMTP 认证失败。"
    assert exc.reason == "auth_failed"


def test_search_page_hasmore_truthful_at_page_size_50(client):
    """60 matching rows, page size 50 → first page hasMore=True, and the
    second page carries the remaining 10 (boundary clamp regression)."""
    from lumirss.main import app

    db = app.state.db

    async def seed():
        await db.migrate()
        for i in range(60):
            await db.execute(
                "INSERT INTO search_library (ref, kind, title, body, url, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    f"clip:{i:04d}",
                    "clip",
                    f"边界条目 {i:04d}",
                    f"body {i:04d}",
                    f"https://example.com/{i:04d}",
                    f"2026-01-{(i % 28) + 1:02d}T00:00:00.{i:06d}Z",
                ),
            )

    run(seed())

    response = client.get(
        "/api/v1/search", params={"q": "边界条目", "limit": 50}
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["library"]) == 50
    assert body["libraryHasMore"] is True
    assert body["libraryNextCursor"]

    second = client.get(
        "/api/v1/search",
        params={
            "q": "边界条目",
            "limit": 50,
            "libraryCursor": body["libraryNextCursor"],
        },
    )
    assert second.status_code == 200
    second_body = second.json()
    assert len(second_body["library"]) == 10
    assert second_body["libraryHasMore"] is False
