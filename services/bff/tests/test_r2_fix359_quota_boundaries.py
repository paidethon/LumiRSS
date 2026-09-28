"""FIX-359 — 整数配额计算溢出 / 负值绕过（边界核验）。

配额执行面与事实（BASELINE_OK 的证据基础）：

- AI 调用配额（ai_quota.claim_ai_call）：唯一写法是事务内
  ``INSERT ... calls=1`` / ``UPDATE calls = calls + 1``——只增不减、
  从 0 起；判定是纯比较 ``current >= max_calls``，无任何算术注入面
  （没有任何 API 接受 usage 增量；全库仅此一处写 ai_usage）；
- 来源上限（user_quotas.maxSources）：判定 ``COUNT(*) < max``，
  COUNT 非负；上限本身只经 ``_normalize_caps`` 写入（正整数、
  1..上限界、bool/负数/0/字符串全部拒绝——布尔→1 强转洞已在
  FIX-039 修复）；
- 管理员/成员上限合成（effective_ai_limits）：取更小者；负数或 0
  的 cap 在解析层即被忽略（不可借负值把限额变成「不拦截」）。

边界：恰好到限 → 拒绝且拒绝不计数；巨值比较精确不崩溃；
remaining 钳到 0 不出负数。
"""

import asyncio
import json
import sqlite3

import pytest

from lumirss.ai_quota import QuotaExceeded, claim_ai_call, usage_snapshot, window_bounds
from lumirss.storage import Database
from lumirss.user_quotas import (
    MAX_AI_DAILY_CAP,
    MAX_SOURCES_CAP,
    QuotaPolicyError,
    UserQuotaStore,
    _normalize_caps,
    effective_ai_limits,
)


def run(coroutine):
    return asyncio.run(coroutine)


def _seed_calls(db_path, window_key, calls):
    """直接改库播种极端计数（只可能由越权写产生；API 无此路径）。"""
    connection = sqlite3.connect(str(db_path))
    try:
        connection.execute(
            "UPDATE ai_usage SET calls = ? WHERE window_key = ?",
            (calls, window_key),
        )
        connection.commit()
    finally:
        connection.close()


def _calls_of(db, window_key):
    row = run(
        db.fetch_one("SELECT calls AS c FROM ai_usage WHERE window_key = ?", (window_key,))
    )
    return int(row["c"]) if row else 0


def test_claim_blocks_exactly_at_limit_and_denial_counts_nothing(tmp_path):
    """max=3：恰 3 个通过；第 4 个（used==max 边界）拒绝，且被拒绝的
    尝试不消耗也不回退名额（仍是 3，边界重试同样拒绝）。"""
    db = Database(tmp_path / "lumi.sqlite")
    key = window_bounds(window="day").key

    async def _attempt():
        try:
            await claim_ai_call(db, window="day", max_calls=3)
            return "granted"
        except QuotaExceeded:
            return "denied"

    async def _four():
        return [await _attempt() for _ in range(4)]

    results = run(_four())
    assert results == ["granted", "granted", "granted", "denied"]
    assert _calls_of(db, key) == 3, "拒绝不计数"
    with pytest.raises(QuotaExceeded):
        run(claim_ai_call(db, window="day", max_calls=3))
    assert _calls_of(db, key) == 3, "边界重试不改变计数"


def test_usage_is_monotone_and_only_incrementable(tmp_path):
    """配额计数只增不减：5 次授予后 calls==5；没有任何路径能让可用
    配额因负增量而升高（claim 的 SQL 只有 +1，从 0 起，无减量端点）。"""
    db = Database(tmp_path / "lumi.sqlite")
    key = window_bounds(window="day").key

    for _ in range(5):
        run(claim_ai_call(db, window="day", max_calls=100))
    assert _calls_of(db, key) == 5

    with pytest.raises(QuotaExceeded):
        run(claim_ai_call(db, window="day", max_calls=5))
    assert _calls_of(db, key) == 5


def test_huge_usage_values_compare_correctly(tmp_path):
    """int64 巨值种子：比较精确、拒绝、不崩溃、拒绝路径不写计数。"""
    db = Database(tmp_path / "lumi.sqlite")
    key = window_bounds(window="day").key
    run(claim_ai_call(db, window="day", max_calls=5))  # 建行
    _seed_calls(db.path, key, 2**63 - 1)

    with pytest.raises(QuotaExceeded) as excinfo:
        run(claim_ai_call(db, window="day", max_calls=5))
    assert excinfo.value.used == 5
    assert _calls_of(db, key) == 2**63 - 1, "拒绝路径绝不写计数"

    # 快照口径：巨值 used 下 remaining 钳 0，不出负数、不崩溃。
    snapshot = run(usage_snapshot(db, "day", 5))
    assert snapshot["used"] == 2**63 - 1
    assert snapshot["remaining"] == 0


def test_over_limit_snapshot_clamps_remaining_at_zero(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    key = window_bounds(window="day").key
    for _ in range(2):
        run(claim_ai_call(db, window="day", max_calls=2))
    snapshot = run(usage_snapshot(db, "day", 2))
    assert snapshot["used"] == 2
    assert snapshot["remaining"] == 0
    # used > max 的越界态（外部种子）同样钳 0。
    _seed_calls(db.path, key, 7)
    snapshot = run(usage_snapshot(db, "day", 2))
    assert snapshot["remaining"] == 0


def test_caps_validation_rejects_non_positive_and_oversized():
    """上限只接受 [1, 界] 内的纯整数：0/负数/bool/字符串/超界全拒——
    负值不可能经写路径把限额变成「不拦截」或负上限。"""
    with pytest.raises(QuotaPolicyError):
        _normalize_caps({"maxSources": 0})
    with pytest.raises(QuotaPolicyError):
        _normalize_caps({"maxSources": -5})
    with pytest.raises(QuotaPolicyError):
        _normalize_caps({"maxSources": True})  # bool 一律拒绝（非业务整数）
    with pytest.raises(QuotaPolicyError):
        _normalize_caps({"aiQuotaPerDay": "50"})
    with pytest.raises(QuotaPolicyError):
        _normalize_caps({"aiQuotaPerDay": 0})
    with pytest.raises(QuotaPolicyError):
        _normalize_caps({"aiQuotaPerDay": -1})
    with pytest.raises(QuotaPolicyError):
        _normalize_caps({"maxSources": MAX_SOURCES_CAP + 1})
    with pytest.raises(QuotaPolicyError):
        _normalize_caps({"aiQuotaPerDay": MAX_AI_DAILY_CAP + 1})
    assert _normalize_caps({"maxSources": 1, "aiQuotaPerDay": MAX_AI_DAILY_CAP}) == {
        "maxSources": 1,
        "aiQuotaPerDay": MAX_AI_DAILY_CAP,
    }


def test_stored_negative_caps_are_ignored_not_converted(tmp_path):
    """即使台账被直接改库写入负 cap JSON（无 API 路径可达），解析层
    也只认正整数——负 cap 被忽略 = 未设限，绝不会经合成把成员自己的
    限额打穿成「不拦截」。"""
    db = Database(tmp_path / "control.sqlite")
    store = UserQuotaStore(db)
    run(store.set_caps(user_id="u359", caps={"aiQuotaPerDay": 10}, updated_by="owner"))
    # 直接改库植入负值（模拟越权写；API 无法产生）。
    connection = sqlite3.connect(str(db.path))
    try:
        connection.execute(
            "UPDATE user_quotas SET caps = ? WHERE user_id = ?",
            (json.dumps({"aiQuotaPerDay": -3, "maxSources": -1}), "u359"),
        )
        connection.commit()
    finally:
        connection.close()

    assert run(store.caps_for("u359")) == {}

    # 合成语义不受负值影响：成员自设限额保持原样（负 cap ≈ 未设限）。
    assert run(effective_ai_limits(db, "u359", window="day", max_calls=50)) == ("day", 50)


def test_effective_ai_limits_compose_by_min(tmp_path):
    db = Database(tmp_path / "control.sqlite")
    store = UserQuotaStore(db)

    # 管理员更低 → 收窄。
    run(store.set_caps(user_id="ua", caps={"aiQuotaPerDay": 10}, updated_by="owner"))
    assert run(effective_ai_limits(db, "ua", window="day", max_calls=50)) == ("day", 10)
    # 成员更低 → 保持成员值。
    run(store.set_caps(user_id="ub", caps={"aiQuotaPerDay": 100}, updated_by="owner"))
    assert run(effective_ai_limits(db, "ub", window="day", max_calls=50)) == ("day", 50)
    # 成员未配置而管理员已设限 → 管理员上限以 day 生效。
    run(store.set_caps(user_id="uc", caps={"aiQuotaPerDay": 7}, updated_by="owner"))
    assert run(effective_ai_limits(db, "uc", window="", max_calls=0)) == ("day", 7)
