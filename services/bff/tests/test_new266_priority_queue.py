"""NEW-266 分段翻译优先队列 — 章节先行/选段先行 + 显式补翻。

- enqueue 保序去重；超每篇上限 422；
- run 只发「队列 ∩ 提交块集合」；已有缓存行零 provider 调用
  （已有结果不重复收费）；队列失效索引如实上报；
- A/B 隔离：alice 的队列对 bob 不可见。
"""

import asyncio
import re

import pytest

from lumirss.ai_settings import AiSettingsStore, AiSettingsUpdate
from lumirss.ai_translation_segments import (
    SegmentInput,
    SegmentTranslationService,
)
from lumirss.entryref import encode_entry_ref
from lumirss.new266_priority_queue import (
    QUEUE_CAP,
    QueueCapExceeded,
    QueueIndexInvalid,
    clear_queue,
    enqueue,
    list_queue,
    remove,
    run_queue,
)
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database
from new2xx_ab import ab_env, seed_entry  # noqa: F401

run = asyncio.run


@pytest.fixture(autouse=True)
def _allow_fixture_endpoints(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LUMIRSS_FETCH_ALLOW_PRIVATE_HOSTS", "127.0.0.1,ai.local")


def _echo_provider(calls):
    async def factory(base_url, model):
        calls["n"] += 1

        class FakeProvider:
            async def complete(self, messages):
                markers = re.findall(
                    r"^<<<BLOCK (\d+)>>>", messages[-1]["content"], re.M
                )
                return "\n\n".join(
                    f"<<<BLOCK {int(i)}>>>\n译{int(i)}。" for i in markers
                )

        return FakeProvider()

    return factory


def _make(tmp_path, calls):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    settings = AiSettingsStore(db)
    run(settings.save(AiSettingsUpdate(baseUrl="http://127.0.0.1:9/v1", model="m1")))
    service = SegmentTranslationService(
        db=db,
        settings_store=settings,
        provider_factory=_echo_provider(calls),
        secrets=SecretsStore(tmp_path / "secrets.json"),
    )
    return service, db


def test_enqueue_order_dedupe_and_cap(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    entries = run(enqueue(db, "e1.n266a", [3, 1, 3, 0]))
    assert [e.index for e in entries] == [3, 1, 0]  # 重复 3 是 no-op 保位

    run(enqueue(db, "e1.n266a", [2]))  # 追加不移动已有位置
    entries = run(list_queue(db, "e1.n266a"))
    assert [e.index for e in entries] == [3, 1, 0, 2]

    with pytest.raises(QueueIndexInvalid):
        run(enqueue(db, "e1.n266a", [64]))
    with pytest.raises(QueueIndexInvalid):
        run(enqueue(db, "e1.n266a", [-1]))

    # 恰好到上限（64 = 全部合法索引）允许；守卫用缩小上限验证（整体
    # 拒绝，不部分写入）
    run(clear_queue(db, "e1.n266a"))
    entries = run(enqueue(db, "e1.n266a", list(range(QUEUE_CAP))))
    assert len(entries) == QUEUE_CAP
    run(remove(db, "e1.n266a", 0))
    import lumirss.new266_priority_queue as pq_module

    original_cap = pq_module.QUEUE_CAP
    try:
        pq_module.QUEUE_CAP = QUEUE_CAP - 1
        with pytest.raises(QueueCapExceeded):
            run(enqueue(db, "e1.n266a", [0]))
    finally:
        pq_module.QUEUE_CAP = original_cap
    assert len(run(list_queue(db, "e1.n266a"))) == QUEUE_CAP - 1


def test_remove_and_clear(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(enqueue(db, "e1.n266b", [0, 1, 2]))
    assert run(remove(db, "e1.n266b", 1)) is True
    assert run(remove(db, "e1.n266b", 1)) is False
    assert [e.index for e in run(list_queue(db, "e1.n266b"))] == [0, 2]
    assert run(clear_queue(db, "e1.n266b")) == 2
    assert run(list_queue(db, "e1.n266b")) == []


def test_run_queue_only_missing_and_no_recharge(tmp_path):
    calls = {"n": 0}
    service, db = _make(tmp_path, calls)
    ref = encode_entry_ref("e1.n266c")
    blocks = [
        SegmentInput(index=0, text="Chapter one."),
        SegmentInput(index=1, text="Chapter two."),
        SegmentInput(index=2, text="Chapter three."),
    ]

    # 只优先翻当前章节（块 2），之后追加其余
    run(enqueue(db, ref, [2]))
    result = run(run_queue(db, service, ref, blocks))
    assert result["queuedCount"] == 1
    assert result["skippedMissingText"] == []
    assert result["queuedStates"][0].index == 2
    assert result["queuedStates"][0].translated_text == "译2。"
    assert calls["n"] == 1

    # 追加块 0、1 → 只有它们发 provider；块 2 已有结果零调用
    # （队列登记顺序是 2,0,1 —— 2 先登记）
    run(enqueue(db, ref, [0, 1]))
    result = run(run_queue(db, service, ref, blocks))
    assert result["queuedCount"] == 3
    assert [s.index for s in result["queuedStates"]] == [2, 0, 1]
    assert result["queuedStates"][0].cached is True
    assert calls["n"] == 2  # 队列 0/1 一次批量；块 2 未重发

    # 队列有 5 但块集合没有 5 → 如实上报 skippedMissingText
    run(enqueue(db, ref, [5]))
    result = run(run_queue(db, service, ref, blocks))
    assert result["skippedMissingText"] == [5]
    assert calls["n"] == 2  # 无新增调用

    # 再跑一遍全命中 → 零 provider 调用
    result = run(run_queue(db, service, ref, blocks))
    assert result["queuedCount"] == 3
    assert all(s.cached for s in result["queuedStates"])
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# API 行为
# ---------------------------------------------------------------------------


def _seed_api(client, tmp_path, entry_key: str, calls: dict):
    ref = encode_entry_ref(f"e1.{entry_key}")

    async def run_seed():
        from lumirss.main import app as lumi_app

        db = lumi_app.state.db
        await db.migrate()
        settings = AiSettingsStore(db)
        await settings.save(
            AiSettingsUpdate(baseUrl="http://127.0.0.1:9/v1", model="m1")
        )
        service = SegmentTranslationService(
            db=db,
            settings_store=settings,
            provider_factory=_echo_provider(calls),
            secrets=SecretsStore(str(tmp_path / f"{entry_key}-secrets.json")),
        )
        lumi_app.state.segment_translation_service = service

    run(run_seed())
    return ref


def test_api_priority_queue_roundtrip(client, tmp_path):
    calls = {"n": 0}
    ref = _seed_api(client, tmp_path, "n266api", calls)

    put = client.put(
        f"/api/v1/entries/{ref}/translation/priority-queue",
        json={"indexes": [1, 0]},
    )
    assert put.status_code == 200, put.text
    assert [e["index"] for e in put.json()["queue"]] == [1, 0]

    listed = client.get(f"/api/v1/entries/{ref}/translation/priority-queue")
    assert [e["index"] for e in listed.json()["queue"]] == [1, 0]

    remove = client.delete(f"/api/v1/entries/{ref}/translation/priority-queue/0")
    assert remove.status_code == 200
    assert (
        client.delete(f"/api/v1/entries/{ref}/translation/priority-queue/0").status_code
        == 404
    )

    # run：按队列顺序翻译
    made = client.post(
        f"/api/v1/entries/{ref}/translation/priority-queue/run",
        json={
            "blocks": [
                {"index": 0, "text": "Alpha."},
                {"index": 1, "text": "Beta."},
            ]
        },
    )
    assert made.status_code == 200, made.text
    body = made.json()
    assert body["queuedCount"] == 1  # 队列里只剩 1
    assert body["queuedStates"][0]["translatedText"] == "译1。"
    assert calls["n"] == 1

    bad = client.put(
        f"/api/v1/entries/{ref}/translation/priority-queue",
        json={"indexes": [99]},
    )
    assert bad.status_code == 422

    cleared = client.delete(f"/api/v1/entries/{ref}/translation/priority-queue")
    assert cleared.status_code == 200
    assert (
        client.get(f"/api/v1/entries/{ref}/translation/priority-queue").json()["queue"]
        == []
    )


# ---------------------------------------------------------------------------
# A/B 隔离
# ---------------------------------------------------------------------------


def test_ab_priority_queue_isolated(ab_env):  # noqa: F811
    env = ab_env
    client = env["client"]
    ref = encode_entry_ref("e1.new266ab")
    seed_entry(env, "a", "new266ab")
    seed_entry(env, "b", "new266ab")

    put_a = client.put(
        f"/api/v1/entries/{ref}/translation/priority-queue",
        json={"indexes": [0]},
        headers=env["a"],
    )
    assert put_a.status_code == 200, put_a.text

    a_view = client.get(
        f"/api/v1/entries/{ref}/translation/priority-queue", headers=env["a"]
    ).json()["queue"]
    b_view = client.get(
        f"/api/v1/entries/{ref}/translation/priority-queue", headers=env["b"]
    ).json()["queue"]
    assert [e["index"] for e in a_view] == [0]
    assert b_view == []  # bob 看不到 alice 的队列
