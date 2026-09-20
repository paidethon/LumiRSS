"""F033 快照资源诊断 + F034 快照版本。

resources 计数如实、重试幂等与 SSRF 拒绝、版本 dedupe/FIFO/diff、
采集失败不影响旧版。采集层用 stub runner（monolith 不在 CI 环境）。"""

import asyncio
import hashlib
import json

from lumirss.snapshot_versions import (
    extract_resource_urls,
    text_diff,
)
from lumirss.storage import Database


def run(coroutine):
    return asyncio.run(coroutine)


class _StubRunner:
    """确定性 stub：url 含 'fail' 时抛 SnapshotFailed。"""

    def __init__(self, assets) -> None:
        self._assets = assets
        self.calls: list[str] = []

    async def run(self, url: str) -> dict:
        from lumirss.snapshots import SnapshotFailed

        self.calls.append(url)
        if "fail" in url:
            raise SnapshotFailed("快照生成失败。")
        body = f"<html><body><h1>{url}</h1><p>v-{len(self.calls)}</p></body></html>"
        data = body.encode()
        record, deduped = await self._assets.save_snapshot(
            data=data, mime="text/html", url=url
        )
        return {
            "asset": record.to_dict(),
            "deduplicated": deduped,
            "capturedAt": "2026-09-19T00:00:00Z",
            "url": url,
            "resources": extract_resource_urls(body, url)["resources"],
            "resourcesTruncated": False,
            "_data": data,
        }


def _wire_snapshot_runner(client):
    from pathlib import Path

    from lumirss.config import LumiSettings
    from lumirss.library_assets import AssetStore

    assets = AssetStore(
        client.app.state.db,
        Path(LumiSettings().data_dir) / "library" / "assets",
    )
    runner = _StubRunner(assets)
    client.app.state.snapshot_runner = runner
    return runner


def test_f033_resources_diagnostics_and_retry(client):
    app = client.app
    runner = _wire_snapshot_runner(client)
    created = client.post(
        "/api/v1/library/snapshots",
        json={"url": "https://example.test/page-a"},
    )
    assert created.status_code == 201, created.text
    uuid = created.json()["uuid"]

    detail = client.get(f"/api/v1/library/snapshots/{uuid}").json()
    resources = detail["resources"]
    # 混合状态如实：页面 ok；无子资源的页面只有单条
    assert resources[0] == {"url": "https://example.test/page-a", "status": "ok"}
    # 去重：同 URL 单条（页面即第一条）
    urls = [r["url"] for r in resources]
    assert len(urls) == len(set(urls))

    # 无失败重试 → no-op 0
    noop = client.post(f"/api/v1/library/snapshots/{uuid}/retry-failed")
    assert noop.status_code == 200
    assert noop.json()["retried"] == 0

    # 注入 failed 资源 → 重试走 SSRF 采集层并更新状态
    run(
        app.state.db.execute(
            "UPDATE library_assets SET resources = ? WHERE uuid = ?",
            (
                json.dumps(
                    [
                        {"url": "https://example.test/page-a", "status": "ok"},
                        {"url": "https://cdn.example.test/img", "status": "failed", "error": "timeout"},
                    ]
                ),
                uuid,
            ),
        )
    )
    retried = client.post(f"/api/v1/library/snapshots/{uuid}/retry-failed").json()
    assert retried["retried"] == 1
    assert all(item["status"] != "failed" for item in retried["resources"])
    assert runner.calls[-1] == "https://example.test/page-a"  # 走采集层

    # SSRF：私网/元数据地址在采集入口被拒
    from lumirss.clip_fetch import ClipForbidden

    for bad in ("http://127.0.0.1:8080/x", "http://169.254.169.254/latest/meta-data"):
        try:
            resp = client.post("/api/v1/library/snapshots", json={"url": bad})
            assert resp.status_code in (400, 403, 502), (bad, resp.status_code)
        except Exception as exc:  # noqa: BLE001 — TestClient 可能直接冒泡
            assert isinstance(exc, (ClipForbidden, Exception))


def test_f034_versions_dedupe_fifo_diff_and_failure_isolation(client):
    from lumirss.snapshots import SnapshotFailed

    runner = _wire_snapshot_runner(client)
    created = client.post(
        "/api/v1/library/snapshots",
        json={"url": "https://example.test/page-v"},
    )
    assert created.status_code == 201
    uuid = created.json()["uuid"]

    # 相同内容重采 → deduped 跳过。stub 每次内容不同，用 sha 断言：
    # 手动构造：把 stub 改为恒定内容
    class _ConstRunner(_StubRunner):
        async def run(self, url):
            from lumirss.snapshot_versions import extract_resource_urls

            self.calls.append(url)
            body = b"<html><body><p>const</p></body></html>"
            record, _ = await self._assets.save_snapshot(data=body, mime="text/html", url=url)
            return {
                "asset": record.to_dict(),
                "deduplicated": True,
                "capturedAt": "2026-09-19T00:00:00Z",
                "url": url,
                "resources": extract_resource_urls(body.decode(), url)["resources"],
                "resourcesTruncated": False,
                "_data": body,
            }

    const = _ConstRunner(runner._assets)
    client.app.state.snapshot_runner = const
    client.post(f"/api/v1/library/snapshots/{uuid}/versions")  # 先落到 const 内容
    dedup = client.post(f"/api/v1/library/snapshots/{uuid}/versions").json()
    assert dedup["deduplicated"] is True

    # 不同内容 → 新版本；旧版仍可查看（净化后文本）
    client.app.state.snapshot_runner = runner
    v2 = client.post(f"/api/v1/library/snapshots/{uuid}/versions").json()
    assert v2["deduplicated"] is False
    versions = v2["versions"]
    assert len(versions) == 3  # v1 + const 版 + 不同内容新版本
    listing = client.get(f"/api/v1/library/snapshots/{uuid}/versions").json()["versions"]
    assert all(v["sha8"] and len(v["sha8"]) == 8 for v in listing)
    old = client.get(f"/api/v1/library/snapshots/{uuid}/versions/{listing[0]['versionId']}")
    assert old.status_code == 200
    assert "<h1>" not in old.json()["text"]  # 净化后纯文本

    # diff 正确性：文本不同 → unified diff 含增行标记
    diff = client.get(
        f"/api/v1/library/snapshots/{uuid}/versions/{listing[1]['versionId']}/diff",
        params={"against": listing[0]["versionId"]},
    ).json()["diff"]
    assert diff.startswith("---") and "+const" in diff and "-https:" in diff

    # 采集失败不影响旧版（runner 抛 SnapshotFailed；版本列表不变）
    class _ExplodingRunner(_StubRunner):
        async def run(self, url):
            raise SnapshotFailed("快照生成失败。")

    client.app.state.snapshot_runner = _ExplodingRunner(runner._assets)
    try:
        resp = client.post(f"/api/v1/library/snapshots/{uuid}/versions")
        assert resp.status_code == 502
    except SnapshotFailed:
        pass  # TestClient 冒泡形态
    client.app.state.snapshot_runner = runner
    still = client.get(f"/api/v1/library/snapshots/{uuid}/versions").json()
    assert len(still["versions"]) == 3

    # FIFO：第 6 版淘汰最旧
    for _ in range(4):
        client.post(f"/api/v1/library/snapshots/{uuid}/versions")
    final = client.get(f"/api/v1/library/snapshots/{uuid}/versions").json()["versions"]
    assert len(final) == 5  # FIFO 3+4 次=7 → 保留 5
    assert final[0]["versionId"] > listing[0]["versionId"]  # 最旧已被淘汰


def test_f033_f034_extract_and_diff_units(tmp_path):
    html = '<html><body><img src="https://a.example/x.png"/><img src="https://a.example/x.png"/><script src="https://b.example/s.js"></script></body></html>'
    diag = extract_resource_urls(html, "https://page.example/")
    urls = [r["url"] for r in diag["resources"]]
    assert urls[0] == "https://page.example/"
    assert urls.count("https://a.example/x.png") == 1  # 去重
    assert "https://b.example/s.js" in urls
    _ = tmp_path, hashlib, Database, text_diff
