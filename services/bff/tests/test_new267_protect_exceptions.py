"""NEW-267 专有名词保护例外 — 当前任务级的不翻译豁免。

- 全局 protect=1 术语默认保护（N083）；例外只豁免「这一篇」；
- 例外生效后新生成不再带该术语的保护（prompt 与还原均不含），
  其他条目不受影响；
- 既有缓存译文不被悄悄改写；
- hits：例外术语命中多少个不同源段（只读，大小写不敏感）；
- A/B 隔离。
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
from lumirss.glossary import GlossaryStore
from lumirss.new267_protect_exceptions import (
    EXCEPTION_CAP,
    ProtectCapExceeded,
    ProtectTermInvalid,
    exception_hits,
    excluded_terms,
    list_exceptions,
    register,
    remove,
)
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database
from new2xx_ab import ab_env, seed_entry  # noqa: F401

run = asyncio.run


@pytest.fixture(autouse=True)
def _allow_fixture_endpoints(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LUMIRSS_FETCH_ALLOW_PRIVATE_HOSTS", "127.0.0.1,ai.local")


def _provider_translating_literals(calls):
    """回显 provider：保留输入中的原样词（不保护时会被「翻译掉」）。"""

    async def factory(base_url, model):
        calls["n"] += 1

        class FakeProvider:
            async def complete(self, messages):
                system = messages[0]["content"]
                user = messages[-1]["content"]
                kept = re.findall(r"Preserve these exact strings.*?: (.*?)(?:\.|$)", system)
                markers = re.findall(r"^<<<BLOCK (\d+)>>>", user, re.M)
                chunks = []
                for i in markers:
                    literal = " ".join(kept) if kept else f"译{int(i)}"
                    chunks.append(f"<<<BLOCK {i}>>>\n[{literal}] {int(i)} done")
                return "\n\n".join(chunks)

        return FakeProvider()

    return factory


def _make(tmp_path, calls):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    settings = AiSettingsStore(db)
    run(settings.save(AiSettingsUpdate(baseUrl="http://127.0.0.1:9/v1", model="m1")))
    run(GlossaryStore(db).create("QuantumLeap", "产品名", protect=True))
    service = SegmentTranslationService(
        db=db,
        settings_store=settings,
        provider_factory=_provider_translating_literals(calls),
        secrets=SecretsStore(tmp_path / "secrets.json"),
    )
    return service, db


def test_exception_scopes_protection_to_one_entry(tmp_path):
    calls = {"n": 0}
    service, db = _make(tmp_path, calls)
    ref_exc = encode_entry_ref("e1.n267exc")
    ref_other = encode_entry_ref("e1.n267oth")
    blocks = [SegmentInput(index=0, text="QuantumLeap launched today.")]

    # 默认：两个条目的生成 prompt 都带保护指令
    run(service.generate(ref_exc, blocks))
    run(service.generate(ref_other, blocks))
    assert calls["n"] == 2

    # 登记例外 → 仅这一篇的新生成不带保护
    item = run(register(db, ref_exc, "QuantumLeap"))
    assert item.term == "QuantumLeap"
    assert run(excluded_terms(db, ref_exc)) == {"QuantumLeap"}
    assert run(excluded_terms(db, ref_other)) == set()

    # 源文本变化使缓存身份轮换，生成重新发生
    changed = [SegmentInput(index=0, text="QuantumLeap launched tomorrow.")]
    states_exc = run(service.generate(ref_exc, changed))
    states_other = run(service.generate(ref_other, changed))
    assert calls["n"] == 4
    # 例外篇：protect 指令消失（provider 收到的 system 无 Preserve）
    # → 译文按普通翻译产出；另一篇仍带保护指令
    assert states_exc[0].protected_terms == ()
    assert states_other[0].protected_terms != ()

    # 撤销例外 → 恢复全局保护
    assert run(remove(db, ref_exc, "QuantumLeap")) is True
    assert run(remove(db, ref_exc, "QuantumLeap")) is False
    assert run(excluded_terms(db, ref_exc)) == set()


def test_validation_idempotent_and_hits(tmp_path):
    calls = {"n": 0}
    service, db = _make(tmp_path, calls)
    ref = encode_entry_ref("e1.n267hits")
    run(
        service.generate(
            ref,
            [
                SegmentInput(index=0, text="QuantumLeap one."),
                SegmentInput(index=1, text="quantumleap two."),
                SegmentInput(index=2, text="unrelated."),
            ],
        )
    )
    with pytest.raises(ProtectTermInvalid):
        run(register(db, ref, "   "))
    with pytest.raises(ProtectTermInvalid):
        run(register(db, ref, "x" * 201))

    first = run(register(db, ref, "QuantumLeap"))
    again = run(register(db, ref, " QuantumLeap "))
    assert again.term == first.term  # 幂等

    hits = {h["term"]: h["hitSegments"] for h in run(exception_hits(db, ref))}
    assert hits["QuantumLeap"] == 2  # 大小写不敏感：块 0 + 块 1，块 2 未命中

    items = run(list_exceptions(db, ref))
    assert [i.term for i in items] == ["QuantumLeap"]


def test_exception_cap(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    ref = encode_entry_ref("e1.n267cap")
    for i in range(EXCEPTION_CAP):
        run(register(db, ref, f"term-{i:03d}"))
    with pytest.raises(ProtectCapExceeded):
        run(register(db, ref, "overflow"))


# ---------------------------------------------------------------------------
# API 行为
# ---------------------------------------------------------------------------


def test_api_protect_exceptions_roundtrip(client):
    ref = encode_entry_ref("e1.n267api")
    made = client.post(
        f"/api/v1/entries/{ref}/translation/protect-exceptions",
        json={"term": "Kubernetes"},
    )
    assert made.status_code == 200, made.text

    dup = client.post(
        f"/api/v1/entries/{ref}/translation/protect-exceptions",
        json={"term": "Kubernetes"},
    )
    assert dup.status_code == 200

    view = client.get(f"/api/v1/entries/{ref}/translation/protect-exceptions")
    body = view.json()
    assert [e["term"] for e in body["exceptions"]] == ["Kubernetes"]

    bad = client.post(
        f"/api/v1/entries/{ref}/translation/protect-exceptions", json={"term": "  "}
    )
    assert bad.status_code == 422

    removed = client.delete(
        f"/api/v1/entries/{ref}/translation/protect-exceptions/Kubernetes"
    )
    assert removed.status_code == 200
    assert (
        client.delete(
            f"/api/v1/entries/{ref}/translation/protect-exceptions/Kubernetes"
        ).status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/entries/{ref}/translation/protect-exceptions").json()[
            "exceptions"
        ]
        == []
    )


# ---------------------------------------------------------------------------
# A/B 隔离
# ---------------------------------------------------------------------------


def test_ab_protect_exceptions_isolated(ab_env):  # noqa: F811
    env = ab_env
    client = env["client"]
    ref = encode_entry_ref("e1.new267ab")
    seed_entry(env, "a", "new267ab")
    seed_entry(env, "b", "new267ab")

    made = client.post(
        f"/api/v1/entries/{ref}/translation/protect-exceptions",
        json={"term": "AliceTerm"},
        headers=env["a"],
    )
    assert made.status_code == 200, made.text

    a_view = client.get(
        f"/api/v1/entries/{ref}/translation/protect-exceptions", headers=env["a"]
    ).json()
    b_view = client.get(
        f"/api/v1/entries/{ref}/translation/protect-exceptions", headers=env["b"]
    ).json()
    assert [e["term"] for e in a_view["exceptions"]] == ["AliceTerm"]
    assert b_view["exceptions"] == [] and b_view["hits"] == []
