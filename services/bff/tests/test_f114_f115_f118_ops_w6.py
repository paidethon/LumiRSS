"""F114/F115/F118/F111 —— W6 运维与历史域（后端）。"""

import asyncio
import json
import zipfile
from datetime import UTC, datetime, timedelta

from lumirss.settings_history import SettingsHistoryStore, compute_diff
from lumirss.storage_retention import (
    load_retention,
    retention_apply,
    retention_preview,
    save_retention,
)


def run(coroutine):
    return asyncio.run(coroutine)


# ---- F114 -------------------------------------------------------------------


def _seed_ai_versions(db, rows):
    run(db.migrate())
    for i, (created_at, summary) in enumerate(rows):
        run(
            db.execute(
                "INSERT INTO ai_summary_versions (id, entry_ref, content_hash, summary, model, created_at) VALUES (?, ?, ?, ?, 'm', ?)",
                (f"v{i}", f"rss:v{i}", f"h{i}", summary, created_at),
            )
        )


def _seed_task_log(db, rows):
    for i, (created_at,) in enumerate(rows):
        run(
            db.execute(
                "INSERT INTO ai_task_log (id, kind, status, created_at) VALUES (?, 'summary', 'done', ?)",
                (f"t{i}", created_at),
            )
        )


def test_f114_retention_boundary_preview_apply_consistency(client):
    db = client.app.state.db
    now = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)
    # 30 天边界：恰 30 天前 → 保留；30 天 + 1 秒 → 清理
    boundary_keep = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    boundary_drop = (now - timedelta(days=30, seconds=1)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    _seed_ai_versions(db, [(boundary_keep, "恰好 30 天（保留）"), (boundary_drop, "超 30 天（清理）")])
    log_keep = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    log_drop = (now - timedelta(days=7, seconds=1)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    _seed_task_log(db, [(log_keep,), (log_drop,), (log_drop,)])
    run(save_retention(db, {"enabled": True, "aiVersionsDays": 30, "taskLogDays": 7}))

    preview = run(retention_preview(db, now))
    assert preview["aiVersions"]["count"] == 1
    assert preview["aiVersions"]["bytes"] == len("超 30 天（清理）")
    assert preview["taskLog"]["count"] == 2
    # 保护类如实列出（负向：计数恒 0，不进删除路径）
    assert preview["excluded"]["credentials"] == "保护不清理"
    assert preview["excluded"]["runningJobs"] == "保护不清理"
    assert preview["excluded"]["entries"] == 0
    assert "24" in preview["quizNote"]

    # 预览与应用一致
    result = run(retention_apply(db, now))
    assert result["deleted"]["aiVersions"] == 1
    assert result["deleted"]["taskLog"] == 2
    row = run(db.fetch_one("SELECT COUNT(*) AS n FROM ai_summary_versions"))
    assert int(row["n"]) == 1

    # 关闭 = no-op
    run(save_retention(db, {"enabled": False, "aiVersionsDays": 30, "taskLogDays": 7}))
    noop = run(retention_apply(db, now))
    assert noop["deleted"] == {"aiVersions": 0, "taskLog": 0}
    assert "no-op" in noop["note"]

    # 配置持久（重启语义：重新 load 一致）
    cfg = run(load_retention(db))
    assert cfg["enabled"] is False and cfg["aiVersionsDays"] == 30

    # 越界天数被收敛为 None（30–365 / 7–180 窗口外不启用该类）
    run(save_retention(db, {"enabled": True, "aiVersionsDays": 10, "taskLogDays": 999}))
    cfg2 = run(load_retention(db))
    assert cfg2["aiVersionsDays"] is None and cfg2["taskLogDays"] is None


def test_f114_retention_routes(client):
    put = client.put(
        "/api/v1/storage/retention",
        content=json.dumps({"enabled": True, "aiVersionsDays": 90, "taskLogDays": 30}),
        headers={"content-type": "application/json"},
    )
    assert put.status_code == 200, put.text
    assert put.json() == {"enabled": True, "aiVersionsDays": 90, "taskLogDays": 30}

    got = client.get("/api/v1/storage/retention")
    assert got.json()["enabled"] is True

    preview = client.post("/api/v1/storage/retention/preview")
    assert preview.status_code == 200
    assert "excluded" in preview.json()

    apply_resp = client.post("/api/v1/storage/retention/apply")
    assert apply_resp.status_code == 200
    assert set(apply_resp.json()["deleted"].keys()) == {"aiVersions", "taskLog"}


# ---- F115 -------------------------------------------------------------------


class _FakeJob:
    def __init__(self, jobs, job_id):
        self._jobs = jobs
        self._id = job_id

    async def get(self, job_id):
        return self._jobs.get(job_id)


def _make_backup_zip(path, manifest):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("data/lumi.sqlite", b"sqlite-bytes")


def test_f115_backup_compare_identical_delta_damaged_readonly(client, tmp_path, monkeypatch):
    from lumirss.routers import backup as backup_router

    manifest_a = {
        "backupSchemaVersion": 2,
        "lumiDbSchemaVersion": 65,
        "componentCounts": {"lumi.sqlite": 3, "freshrss-data": 5},
    }
    manifest_b = {
        "backupSchemaVersion": 2,
        "lumiDbSchemaVersion": 65,
        "componentCounts": {"lumi.sqlite": 3, "freshrss-data": 7},
    }
    path_a = tmp_path / "a.backup"
    path_b = tmp_path / "b.backup"
    path_bad = tmp_path / "bad.backup"
    _make_backup_zip(path_a, manifest_a)
    _make_backup_zip(path_b, manifest_b)
    with zipfile.ZipFile(path_bad, "w") as archive:
        archive.writestr("manifest.json", "{not json")
    with zipfile.ZipFile(tmp_path / "evil.backup", "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "backupSchemaVersion": 2,
                    "lumiDbSchemaVersion": 1,
                    "componentCounts": {"<script>alert(1)</script>": 1, "lumi.sqlite": 1},
                }
            ),
        )

    mtime_a = path_a.stat().st_mtime_ns
    size_a = path_a.stat().st_size

    jobs = {
        "a": {"status": "succeeded", "summary": json.dumps({"localPath": str(path_a)})},
        "b": {"status": "succeeded", "summary": json.dumps({"localPath": str(path_b)})},
        "bad": {"status": "succeeded", "summary": json.dumps({"localPath": str(path_bad)})},
        "evil": {
            "status": "succeeded",
            "summary": json.dumps({"localPath": str(tmp_path / "evil.backup")}),
        },
    }
    monkeypatch.setattr(backup_router, "_get_backup_jobs", lambda request: _FakeJob(jobs, "a"))

    # 相同备份 → identical
    same = client.post("/api/v1/backups/compare", json={"aId": "a", "bId": "a"})
    assert same.status_code == 200
    assert same.json()["identical"] is True

    # 不同计数 → delta 正确
    diff = client.post("/api/v1/backups/compare", json={"aId": "a", "bId": "b"})
    data = diff.json()
    assert data["identical"] is False
    cats = {c["name"]: c for c in data["categories"]}
    assert cats["freshrss-data"]["delta"] == -2
    assert cats["freshrss-data"]["aCount"] == 5 and cats["freshrss-data"]["bCount"] == 7
    assert data["schemaVersions"] == {"a": 65, "b": 65}

    # 损坏 manifest → 该侧 incomparable（诚实；绝不显示为 0 计数）
    damaged = client.post("/api/v1/backups/compare", json={"aId": "a", "bId": "bad"})
    ddata = damaged.json()
    assert ddata["identical"] is False
    assert ddata["categories"] == []
    assert len(ddata["incomparable"]) == 1 and "损坏" in ddata["incomparable"][0]

    # 恶意段名 → 不进比较面，只进 incomparable 提示（转义由前端渲染层承担）
    evil = client.post("/api/v1/backups/compare", json={"aId": "a", "bId": "evil"}).json()
    assert all(c["name"] != "<script>alert(1)</script>" for c in evil["categories"])
    assert any("未知" in item for item in evil["incomparable"])

    # 只读负向：比较后备份文件 mtime/size 不变
    assert path_a.stat().st_mtime_ns == mtime_a
    assert path_a.stat().st_size == size_a


# ---- F118 -------------------------------------------------------------------


def test_f118_timeline_merge_order_limit_and_secret_free(client):
    db = client.app.state.db
    run(db.migrate())
    # 三个来源 + 一个含「秘密」的行（构造负向 fixture）
    run(
        db.execute(
            "INSERT INTO backup_jobs (id, type, status, created_at, started_at, finished_at, safe_error) VALUES ('j1', 'full', 'succeeded', '2026-09-18T01:00:00+00:00', '2026-09-18T01:00:00+00:00', '2026-09-18T01:05:00+00:00', NULL)",
            (),
        )
    )
    run(
        db.execute(
            "INSERT INTO ai_task_log (id, kind, status, model, created_at) VALUES ('a1', 'summary', 'failed', 'm', '2026-09-18T05:00:00+00:00')",
            (),
        )
    )
    run(
        db.execute(
            "UPDATE ai_task_log SET error_type = 'AiAuthError' WHERE id = 'a1'",
            (),
        )
    )
    run(
        db.execute(
            "INSERT INTO import_batches (id, kind, created_at, counts_json, errors_json, retry_payload_json) VALUES ('i1', 'opml', '2026-09-18T09:00:00+00:00', '{\"created\": 3, \"skipped\": 1, \"failed\": 2}', '{}', '[]')",
            (),
        )
    )
    # 秘密 fixture：把「密码」塞进一个本不显示的字段
    run(
        db.execute(
            "INSERT INTO import_batches (id, kind, created_at, counts_json, errors_json, retry_payload_json) VALUES ('i-secret', 'md_notes', '2026-09-18T09:30:00+00:00', '{}', '{\"items\": [{\"error\": \"SUPER_SECRET_VALUE_123\"}]}', '[]')",
            (),
        )
    )
    run(
        db.execute(
            "INSERT INTO gpt_digest_issues (config_id, issue_key, status, title, body_html, sections_json, refs_json, model, created_at, published_at, updated_at) VALUES (1, '2026-09-17', 'published', '日报标题', '<p>b</p>', '[]', '{}', 'm', '2026-09-17T08:00:00+00:00', '2026-09-17T08:00:00+00:00', '2026-09-17T08:00:00+00:00')",
            (),
        )
    )

    resp = client.get("/api/v1/operations/timeline?limit=100")
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    kinds = {e["kind"] for e in items}
    assert {"backup:full", "ai:summary", "import:opml", "digest:issue"} <= kinds
    # 合并排序：时间倒序
    ats = [e["at"] for e in items]
    assert ats == sorted(ats, reverse=True)
    # 上限
    assert len(items) <= 100
    assert all(len(e["summary"]) <= 120 for e in items)
    # 失败与部分失败如实
    failed_ai = next(e for e in items if e["kind"] == "ai:summary")
    assert failed_ai["status"] == "failed"
    failed_import = next(e for e in items if e["kind"] == "import:opml")
    assert failed_import["status"] == "failed"
    # 秘密不泄露（负向 grep）
    body = resp.text
    assert "SUPER_SECRET_VALUE_123" not in body
    # 空库空态（新 limit 查询一个空时间段仍稳定返回）
    empty = client.get("/api/v1/operations/timeline?limit=1")
    assert empty.status_code == 200


def test_f111_history_secret_key_guard_and_revert_skip(client):
    db = client.app.state.db
    # 秘密键护栏：值绝不落历史（fixture 负向 grep 依据）
    diff = compute_diff(
        {"ai.api_key": "sk-old", "themeMode": "light"},
        {"ai.api_key": "sk-new", "themeMode": "dark"},
    )
    assert diff["ai.api_key"] == {"before": "***", "after": "***"}
    assert diff["themeMode"] == {"before": "light", "after": "dark"}

    # 连续修改后撤销中间笔：只影响目标键；被后续更改的键 skipped 汇报
    # （历史记录由 PATCH 路由写入——与生产路径一致）
    def _patch(body):
        resp = client.patch(
            "/api/v1/settings",
            content=json.dumps(body),
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    current = _patch({"themeMode": "dark", "readerFontSize": 20.0})  # 记录 A（要撤销的）
    _ = current
    _patch({"themeMode": "light"})  # 后续笔：themeMode 被再次更改
    history = run(SettingsHistoryStore(db).list_history(10))
    entry_a = next(
        e
        for e in history
        if e["diff"].get("themeMode", {}).get("after") == "dark"
        and e["diff"].get("readerFontSize", {}).get("after") == 20.0
    )
    resp = client.post(f"/api/v1/settings/history/{entry_a['id']}/revert")
    assert resp.status_code == 200, resp.text
    result = resp.json()
    # themeMode 已被后续更改 → skipped（负向：撤销不全覆盖）
    assert "themeMode" in result["skipped"]
    # readerFontSize 未被后续触碰 → 应用 before 值（只影响目标键）
    assert result["applied"].get("readerFontSize") == 17.0
