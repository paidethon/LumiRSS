"""FIX-246 — 刷新结果绑定运行代次：过期失败不得覆盖最近的成功。

api_sources 的 Atom 端点每次拉取（FreshRSS 轮询/手动拨号）是一次独立
run；两次 run 可以重叠（慢 run A 先启动、快 run B 后启动却先完成）。
旧实现里 A 的失败回写（mark_error）无条件覆盖 last_status——比 B 更晚
到达的过期失败把来源状态从 ok 翻回 fetch_failed（UI 显示最近一次结果
为假）。

契约：run 启动时记录当时代码看到的 last_success_at 作为**运行代次见
证**；mark_error 只在该见证仍然成立（没有被更新的成功改写）时落库。
mark_success 返回它写入的时间戳，同 run 成功后的标志（N130
fallback_used）以该值为见证，依旧必须能落库。
"""

import asyncio

import pytest

from lumirss.api_source_store import ApiSourceStore


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture()
def source_db(tmp_path):
    from lumirss.storage import Database

    db = Database(tmp_path / "fix246.sqlite")
    run(db.migrate())
    return db


@pytest.fixture()
def store(source_db):
    return ApiSourceStore(source_db)


def _create(store, name: str = "代次源"):
    return run(
        store.create(
            name=name,
            endpoint="https://api.example.com/items",
            items_expr="[*]",
            field_map={"id": "id", "title": "name"},
        )
    )


def test_stale_failure_does_not_overwrite_fresher_success(store):
    """慢 run A（见证=None）在快 run B 成功之后才失败 → 失败被丢弃，
    last_status 保持 ok、last_error 不出现。"""
    record = _create(store)
    run(store.mark_success(record.uuid, '"e1"', "<feed/>", "2026-09-01T00:00:00+00:00"))

    rejected = run(
        store.mark_error(
            record.uuid,
            "fetch_failed",
            "迟到的失败（慢 run）",
            success_witness=None,  # A 启动时还没有任何成功
        )
    )
    assert rejected is False, "过期失败不得覆盖最近成功"
    after = run(store.get(record.uuid))
    assert after.last_status == "ok"
    assert after.last_error is None


def test_same_generation_failure_still_records(store):
    """见证仍成立（没有并发成功改写 last_success_at）→ 失败照常落库。"""
    record = _create(store)
    witness = run(
        store.mark_success(record.uuid, '"e1"', "<feed/>", "2026-09-01T00:00:00+00:00")
    )
    accepted = run(
        store.mark_error(
            record.uuid,
            "fetch_failed",
            "本轮真实失败",
            success_witness=witness,
        )
    )
    assert accepted is True
    after = run(store.get(record.uuid))
    assert after.last_status == "fetch_failed"
    assert after.last_error == "本轮真实失败"


def test_failure_without_any_prior_success_records(store):
    """首次 run 失败（见证=None，行里 last_success_at 也是 NULL）→
    条件守卫必须命中 NULL，失败如实落库。"""
    record = _create(store)
    accepted = run(
        store.mark_error(record.uuid, "fetch_failed", "首跑失败", success_witness=None)
    )
    assert accepted is True
    after = run(store.get(record.uuid))
    assert after.last_status == "fetch_failed"


def test_mark_success_returns_run_witness(store):
    """mark_success 返回写入的时间戳——同 run 的后续标志以此为见证。"""
    record = _create(store)
    stamp = run(
        store.mark_success(record.uuid, '"e1"', "<feed/>", "2026-09-01T00:00:00+00:00")
    )
    assert stamp
    after = run(store.get(record.uuid))
    assert after.last_success_at == stamp


def test_post_success_flag_survives_with_own_witness(store):
    """N130 fallback_used：成功之后同 run 写入的标志，以 mark_success
    返回值为见证必须落库（旧凭据提醒不被代次守卫吞掉）。"""
    record = _create(store)
    stamp = run(
        store.mark_success(record.uuid, '"e1"', "<feed/>", "2026-09-01T00:00:00+00:00")
    )
    accepted = run(
        store.mark_error(
            record.uuid,
            "fallback_used",
            "旧凭据在宽限期内被使用",
            success_witness=stamp,
        )
    )
    assert accepted is True
    after = run(store.get(record.uuid))
    assert after.last_status == "fallback_used"
