"""NEW-318 剪藏图片选择器 — 清单体积、勾选丢弃、台账、A/B 隔离。

页面抓取与图片体积探测全部 mock（真实有界管线口径见 test_clip_fetch /
bookmarks_check 测试）；本套件验证选择器行为。
"""

import base64
from dataclasses import dataclass

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册

PAGE_URL = "https://gallery.example/posts/photo-essay"
IMG_A = "https://cdn.gallery.example/a.jpg"
IMG_B = "https://cdn.gallery.example/b.jpg"
IMG_C = "https://cdn.gallery.example/c.gif"
DATA_URI = "data:image/png;base64," + base64.b64encode(b"\x89PNG-tiny").decode()

RAW_HTML = (
    "<html><head><title>图集</title></head><body>"
    "<article>"
    "<h1>影像笔记</h1>"
    f'<p>开头段落<img src="{IMG_A}" alt="首图">继续文字。</p>'
    f'<p><img src="{IMG_B}" alt="图表"></p>'
    f'<p><img src="{IMG_C}"></p>'
    f'<p><img src="{DATA_URI}" alt="内联"></p>'
    "</article>"
    "</body></html>"
)


@dataclass
class _Page:
    html: str
    final_url: str
    content_type: str = "text/html"


def _fake_fetcher():
    async def fetch(url: str):
        return _Page(html=RAW_HTML, final_url=url)

    return fetch


def _failing_fetcher():
    from lumirss.clip_fetch import ClipFetchError

    async def fetch(url: str):
        raise ClipFetchError("页面抓取超时。", "timeout")

    return fetch


def _fake_prober(sizes: dict[str, int | None]):
    async def probe(url: str):
        return sizes.get(url)

    return probe


def _install(ab_env, fetcher, prober) -> None:  # noqa: F811
    ab_env["app"].state.image_picker_fetcher = fetcher
    ab_env["app"].state.image_picker_prober = prober


def _manifest(client, headers, url=PAGE_URL):
    return client.post(
        "/api/v1/library/clips/image-manifest", json={"url": url}, headers=headers
    )


def _curate(client, headers, selected, url=PAGE_URL):
    return client.post(
        "/api/v1/library/clips/curated",
        json={"url": url, "selectedImages": selected},
        headers=headers,
    )


def test_new318_manifest_lists_images_with_estimated_sizes(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    _install(
        ab_env,
        _fake_fetcher(),
        _fake_prober({IMG_A: 120_000, IMG_B: None}),  # C 探测不到 → None；data: 精确
    )
    body = _manifest(client, a).json()
    assert body["imageCount"] == 4
    by_src = {img["src"]: img for img in body["images"]}
    assert by_src[IMG_A]["bytes"] == 120_000
    assert by_src[IMG_B]["bytes"] is None  # 诚实未知，绝不猜数
    assert by_src[IMG_C]["bytes"] is None
    assert by_src[DATA_URI]["bytes"] == len(b"\x89PNG-tiny")  # data: 精确计算
    assert by_src[IMG_A]["alt"] == "首图"
    assert "一个字节都不下载" in body["honestyNote"]


def test_new318_curated_save_keeps_only_selected_images(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    _install(ab_env, _fake_fetcher(), _fake_prober({}))

    result = _curate(client, a, [IMG_A, DATA_URI])
    assert result.status_code == 201, result.text
    body = result.json()
    assert body["created"] is True
    assert body["selectedCount"] == 2
    assert body["clip"]["contentHtml"]
    assert IMG_A in body["clip"]["contentHtml"]
    assert DATA_URI in body["clip"]["contentHtml"]
    assert IMG_B not in body["clip"]["contentHtml"]
    assert IMG_C not in body["clip"]["contentHtml"]
    assert body["clip"]["contentText"].strip()  # 文字保留

    clip_uuid = body["clip"]["ref"].split(":", 1)[1]
    selection = client.get(
        f"/api/v1/library/clips/{clip_uuid}/image-selection", headers=a
    )
    assert selection.status_code == 200
    assert set(selection.json()["selectedImages"]) == {IMG_A, DATA_URI}

    # 勾选了清单里不存在的 URL → 保存成功但如实标注 unknownSelections
    weird = _curate(client, a, [IMG_A, "https://elsewhere.example/x.jpg"])
    assert weird.status_code == 201
    assert weird.json()["unknownSelections"] == ["https://elsewhere.example/x.jpg"]


def test_new318_unreachable_page_fails_honestly(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    _install(ab_env, _failing_fetcher(), _fake_prober({}))
    failed = _manifest(client, a)
    assert failed.status_code == 502
    assert failed.json()["error"]["type"] == "clip_fetch_failed"
    saved = _curate(client, a, [IMG_A])
    assert saved.status_code == 502
    # 没有写入任何剪藏
    listing = client.get("/api/v1/library/clips", headers=a).json()
    assert listing["items"] == []


def test_new318_per_user_isolation_between_accounts(ab_env):  # noqa: F811
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    _install(ab_env, _fake_fetcher(), _fake_prober({}))
    created = _curate(client, a, [IMG_A])
    clip_uuid = created.json()["clip"]["ref"].split(":", 1)[1]

    # B 看不到 A 的勾选台账与剪藏
    assert (
        client.get(f"/api/v1/library/clips/{clip_uuid}/image-selection", headers=b).status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/library/clips/{clip_uuid}", headers=b).status_code == 404
    )

    # B 保存同一 URL：各自剪藏域收敛在各自账户里（A 的台账不被 B 改写）
    mine = _curate(client, b, [IMG_B])
    assert mine.status_code == 201
    b_selection = client.get(
        f"/api/v1/library/clips/{mine.json()['clip']['ref'].split(':', 1)[1]}/image-selection",
        headers=b,
    ).json()
    assert b_selection["selectedImages"] == [IMG_B]
    a_selection = client.get(
        f"/api/v1/library/clips/{clip_uuid}/image-selection", headers=a
    ).json()
    assert a_selection["selectedImages"] == [IMG_A]
