"""FIX-370 — 后台任务创建事务回滚但任务仍已入队（入队顺序核验）。

事实（BASELINE_OK 的证据基础，backup.py BackupEngine.submit_full_backup）：

- 后台任务的「队列」是进程内 asyncio task（``_run_full``），唯一的
  持久载体是 backup_jobs 行；create/start 都是单语句
  ``Database.execute``——逐条自动提交，不存在横跨「insert + 入队」的
  多语句事务，因此不存在「事务回滚但任务已入队」的分离窗口；
- 入队严格发生在 create 与 start 两次落库都成功提交之后；其间任何
  失败都在 create_task 之前抛出，``_busy`` 在 except 释放；
- create 成功而 start 失败留下的是「无 runner 的 queued 行」（反向
  孤儿，has_running 只认 running，不 wedge 新提交），由启动
  interrupted 清扫处置——本文件一并证明该状态不触发任何后台任务。

用 asyncio.create_task 间谍 + 强制 step 失败做行为级证明。
注意：提交与等待必须在同一事件循环里（后台 task 随 loop 存活）。
"""

import asyncio
import sqlite3

import pytest

from lumirss.backup import BackupEngine, BackupJobStore, WebDavSettingsStore
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database

_POLL_TIMEOUT_SECONDS = 30


def _make_freshrss_fixture(base):
    """test_backup.py 同款最小 FreshRSS 目录（备份可成功收尾）。"""
    freshrss = base / "freshrss"
    (freshrss / "users" / "admin").mkdir(parents=True, exist_ok=True)
    (freshrss / "config.php").write_text("<?php return ['db' => 'sqlite'];\n")
    connection = sqlite3.connect(str(freshrss / "users" / "admin" / "db.sqlite"))
    connection.execute("CREATE TABLE feeds (id INTEGER PRIMARY KEY, name TEXT)")
    connection.execute("INSERT INTO feeds (name) VALUES ('Example')")
    connection.commit()
    connection.close()
    return freshrss


@pytest.fixture()
def engine_env(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "lumi.sqlite"
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(db_path))
    monkeypatch.setenv("LUMIRSS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("FRESHRSS_DATA_DIR", str(_make_freshrss_fixture(tmp_path)))
    db = Database(db_path)
    run(db.migrate())
    run(
        db.execute(
            "INSERT INTO lumi_settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("app.settings", '{"schemaVersion":1}', "2026-09-04T00:00:00+00:00"),
        )
    )
    secrets = SecretsStore(data_dir / "secrets.json")

    async def no_client():
        return None

    jobs = BackupJobStore(db)
    engine = BackupEngine(db, jobs, WebDavSettingsStore(db, secrets), no_client)

    real_create_task = asyncio.create_task
    enqueued = []

    def _spy(coro, *args, **kwargs):
        # 入队时刻：持久行必须已提交为 running（顺序证据）。
        connection = sqlite3.connect(str(db_path))
        try:
            rows = connection.execute("SELECT status FROM backup_jobs").fetchall()
        finally:
            connection.close()
        enqueued.append([str(row[0]) for row in rows])
        return real_create_task(coro, *args, **kwargs)

    return db, jobs, engine, enqueued, _spy


def run(coroutine):
    return asyncio.run(coroutine)


async def _await_terminal(jobs, job_id):
    deadline = asyncio.get_running_loop().time() + _POLL_TIMEOUT_SECONDS
    while True:
        current = await jobs.get(job_id)
        if current["status"] in ("succeeded", "failed", "interrupted"):
            return current
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"job {job_id} 未在时限内到达终态: {current}")
        await asyncio.sleep(0.01)


def test_enqueue_happens_only_after_both_writes_committed(engine_env, monkeypatch):
    """成功路径：create_task 被调用那一刻，job 行已提交为 running。"""
    db, jobs, engine, enqueued, spy = engine_env
    monkeypatch.setattr(asyncio, "create_task", spy)

    async def _scenario():
        job = await engine.submit_full_backup("local")
        final = await _await_terminal(jobs, job["id"])
        return job, final

    job, final = run(_scenario())
    assert enqueued, "成功提交必须恰好入队一次"
    for statuses_at_enqueue in enqueued:
        assert statuses_at_enqueue == ["running"], (
            "入队时 create+start 两次落库必须已各自提交"
        )
    assert final["status"] == "succeeded"


def test_create_failure_enqueues_nothing(engine_env, monkeypatch):
    """create 失败 → 异常在入队之前抛出：零 create_task、零 job 行、
    _busy 释放（后续提交可用）。"""
    db, jobs, engine, enqueued, spy = engine_env

    async def _boom(*args, **kwargs):
        raise RuntimeError("create 落库失败")

    monkeypatch.setattr(asyncio, "create_task", spy)
    monkeypatch.setattr(engine._jobs, "create", _boom)

    with pytest.raises(RuntimeError):
        run(engine.submit_full_backup("local"))

    assert enqueued == []
    connection = sqlite3.connect(str(db.path))
    try:
        count = connection.execute("SELECT COUNT(*) FROM backup_jobs").fetchone()
    finally:
        connection.close()
    assert int(count[0]) == 0
    assert engine.running is False


def test_start_failure_enqueues_nothing_and_releases_busy(engine_env, monkeypatch):
    """start 失败 → 无任务入队；留下的是无 runner 的 queued 行
    （has_running 只认 running，不 wedge 后续提交），_busy 释放。"""
    db, jobs, engine, enqueued, spy = engine_env
    jobs_obj = engine._jobs
    original_start = jobs_obj.start

    async def _boom(*args, **kwargs):
        raise RuntimeError("start 落库失败")

    monkeypatch.setattr(asyncio, "create_task", spy)
    monkeypatch.setattr(jobs_obj, "start", _boom)

    with pytest.raises(RuntimeError):
        run(engine.submit_full_backup("local"))

    assert enqueued == []
    connection = sqlite3.connect(str(db.path))
    try:
        rows = connection.execute("SELECT status FROM backup_jobs").fetchall()
    finally:
        connection.close()
    assert [str(row[0]) for row in rows] == ["queued"], (
        "留下的持久行停在 queued（无 runner），绝无已入队的后台任务"
    )
    assert engine.running is False

    # _busy 已释放：恢复 start 后同一 engine 可再次正常提交并跑完。
    monkeypatch.setattr(jobs_obj, "start", original_start)

    async def _recovery():
        job = await engine.submit_full_backup("local")
        return job, await _await_terminal(jobs, job["id"])

    job, final = run(_recovery())
    # submit 返回的是 create 时刻的快照（queued）；落库行此刻已是 running。
    assert final["status"] == "succeeded"
