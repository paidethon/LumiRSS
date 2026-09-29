"""NEW-319 资料重新提取 — 新版完成后选择、旧版可读、失败诚实、A/B 隔离。

fetch 全部 mock（真实有界管线口径见 test_clip_fetch）。
"""

import asyncio
import uuid as _uuid
from dataclasses import dataclass

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册

CLIP_URL = "https://evolving.example/article"


@dataclass
class _Extracted:
    url: str
    final_url: str
    title: str
    byline: str | None
    content_html: str
    content_text: str


def _fake_fetcher(new_title: str, new_text: str):
    async def fetch(url: str):
        return _Extracted(
            url=url,
            final_url=url,
            title=new_title,
            byline=None,
            content_html=f"<article><p>{new_text}</p></article>",
            content_text=new_text,
        )

    return fetch


def _failing_fetcher():
    from lumirss.clip_fetch import ClipFetchError

    async def fetch(url: str):
        raise ClipFetchError("页面返回 HTTP 500。", "fetch_failed")

    return fetch


def _seed_clip(ab_env, who: str) -> str:  # noqa: F811
    clip_uuid = str(_uuid.uuid4())

    async def seed():
        from lumirss.user_scope import user_context

        with user_context(ab_env[who]["userId"]):
            db = ab_env["app"].state.db
            await db.migrate()
            await db.execute(
                "INSERT INTO library_items (uuid, kind, created_at) VALUES (?, 'clip', '2026-09-01T00:00:00Z')",
                (clip_uuid,),
            )
            await db.execute(
                "INSERT INTO library_clips (item_uuid, url, title, byline, content_html, content_text, fetched_at, created_at)"
                " VALUES (?, ?, '旧标题', NULL, '<article><p>旧版正文</p></article>', '旧版正文', '2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z')",
                (clip_uuid, CLIP_URL),
            )

    asyncio.run(seed())
    return clip_uuid


def test_new319_reextract_keeps_old_readable_until_user_applies(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    clip_uuid = _seed_clip(ab_env, "a")
    base = f"/api/v1/library/clips/{clip_uuid}/reextract"
    ab_env["app"].state.reextract_fetcher = _fake_fetcher("新标题", "新版正文：内容更新过了")

    requested = client.post(base, headers=a)
    assert requested.status_code == 200, requested.text
    request_row = requested.json()
    assert request_row["status"] == "done"
    assert request_row["title"] == "新标题"

    # done ≠ 应用：library_clips 完全未动（旧版保持可读）
    async def read_clip():
        from lumirss.user_scope import user_context

        with user_context(a["userId"]):
            db = ab_env["app"].state.db
            return await db.fetch_one(
                "SELECT title, content_text, revised_content_html FROM library_clips WHERE item_uuid = ?",
                (clip_uuid,),
            )

    row = asyncio.run(read_clip())
    assert row is not None
    assert row["title"] == "旧标题"
    assert "旧版正文" in str(row["content_text"])
    assert row["revised_content_html"] is None

    # 列表可见：新版本待选择
    listing = client.get(base, headers=a).json()["requests"]
    assert len(listing) == 1 and listing[0]["applied"] is False

    # 用户显式选择应用 → 修订槽切换，原始版本仍在
    applied = client.post(f"{base}/{request_row['id']}/apply", headers=a)
    assert applied.status_code == 200, applied.text
    row = asyncio.run(read_clip())
    assert "新版正文" in str(row["revised_content_html"])
    assert "旧版正文" in str(row["content_text"])

    # 同一版本不能重复应用（409）
    again = client.post(f"{base}/{request_row['id']}/apply", headers=a)
    assert again.status_code == 409
    assert again.json()["error"]["type"] == "reextract_applied"


def test_new319_failure_recorded_honestly_and_not_applicable(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    clip_uuid = _seed_clip(ab_env, "a")
    base = f"/api/v1/library/clips/{clip_uuid}/reextract"
    ab_env["app"].state.reextract_fetcher = _failing_fetcher()

    failed = client.post(base, headers=a)
    assert failed.status_code == 200  # 请求本身成功落地
    assert failed.json()["status"] == "failed"
    assert "500" in (failed.json()["error"] or "")

    # failed 版本不可应用（409）
    request_id = failed.json()["id"]
    applied = client.post(f"{base}/{request_id}/apply", headers=a)
    assert applied.status_code == 409
    assert applied.json()["error"]["type"] == "reextract_not_done"

    # 目标不存在 → 404
    missing = client.post(
        f"/api/v1/library/clips/{_uuid.uuid4()}/reextract", headers=a
    )
    assert missing.status_code == 404


def test_new319_per_user_isolation_between_accounts(ab_env):  # noqa: F811
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    clip_uuid = _seed_clip(ab_env, "a")
    base = f"/api/v1/library/clips/{clip_uuid}/reextract"
    ab_env["app"].state.reextract_fetcher = _fake_fetcher("新标题", "新版正文")

    created = client.post(base, headers=a)
    request_id = created.json()["id"]

    # B 视角：A 的剪藏与请求都不存在
    assert client.get(base, headers=b).status_code == 404
    assert client.post(f"{base}/{request_id}/apply", headers=b).status_code == 404

    # B 自己的剪藏列表不受影响
    assert client.get("/api/v1/library/clips", headers=b).json()["items"] == []
