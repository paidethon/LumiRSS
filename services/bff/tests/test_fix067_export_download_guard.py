"""FIX-067 守卫：导出/备份下载的路径穿越与跨用户文件读取基线。

两个真实缝隙的钉子（其余导出面——lumi-data.zip、volumes、诊断、
offline-site、portable bundle——均为 per-user 库数据组装或既有守卫：
test_archive_safety（含 FIX-321 多段穿越）+ test_f088 已覆盖）：

1. 远程备份文件名：`_locate_backup_package` 在触碰任何配置/网络之前
   只接受纯文件名（`../x`、`a/b`、`.`、`..` → BackupInvalid；空串
   → BackupNotFound），恶意 WebDAV listing 无法借文件名越界本地
   落盘/读取；
2. 本地备份 job：BackupJobStore 按 per-user 库路由——A 的 jobId 对
   B 不存在（get → None → BackupNotFound），绝不读别人 job 行里
   记录的 localPath（该路径本身也是服务端写入，非客户端输入）。
"""

import asyncio
from types import SimpleNamespace

import pytest

from lumirss.backup import BackupInvalid, BackupJobStore, BackupNotFound
from lumirss.routers.backup import _locate_backup_package
from lumirss.user_scope import RoutingDatabase, user_context


class _Body:
    def __init__(self, source: str, file_name: str | None = None) -> None:
        self.source = source
        self.fileName = file_name
        self.jobId = None


class _FakeRequest:
    def __init__(self) -> None:
        self.app = SimpleNamespace(state=SimpleNamespace())


def test_fix067_remote_backup_filename_plain_name_guard():
    """带路径段/相对段的远程文件名在配置检查前即 BackupInvalid。"""
    request = _FakeRequest()
    for hostile in ("../escape.zip", "a/b.zip", "..", "."):
        with pytest.raises(BackupInvalid):
            asyncio.run(
                _locate_backup_package(_Body("remote", hostile), request)
            )
    # 空文件名：要求补 fileName（BackupNotFound 语义），同样不触路径。
    with pytest.raises(BackupNotFound):
        asyncio.run(_locate_backup_package(_Body("remote", ""), request))


def test_fix067_backup_job_rows_are_per_user(tmp_path):
    """A 创建的备份 job：B 的 store 查不到（None → 404 语义）。"""
    users_root = tmp_path / "users"
    db = RoutingDatabase(tmp_path / "control.sqlite", users_root)

    async def scenario():
        with user_context("fx067a"):
            await db.migrate()
            alice_jobs = BackupJobStore(db)
            job = await alice_jobs.create("full", "local")
        with user_context("fx067b"):
            await db.migrate()
            bob_jobs = BackupJobStore(db)
            assert await bob_jobs.get(job["id"]) is None
        return job["id"]

    job_id = asyncio.run(scenario())

    async def _alice_still_sees() -> None:
        store = BackupJobStore(db)
        assert await store.get(job_id) is not None

    with user_context("fx067a"):
        asyncio.run(_alice_still_sees())


def test_fix067_local_backup_missing_job_is_404_semantics(tmp_path):
    """local 分支：未知 jobId → BackupNotFound（同型 404，不触路径）。"""
    users_root = tmp_path / "users"
    db = RoutingDatabase(tmp_path / "control.sqlite", users_root)

    async def scenario():
        with user_context("fx067a"):
            await db.migrate()
            request = _FakeRequest()
            request.app.state.db = db
            request.app.state.user_services = {}
            body = _Body("local")
            body.jobId = "no-such-job"
            with pytest.raises(BackupNotFound):
                await _locate_backup_package(body, request)

    asyncio.run(scenario())
