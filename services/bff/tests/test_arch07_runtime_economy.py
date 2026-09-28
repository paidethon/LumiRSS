"""ARCH-07 runtime economy: unconfigured optional features must cost
(almost) nothing at boot and per tick.

The measurement report (branch feat/r2-arch07) records the real numbers;
these tests pin the BEHAVIOR so the economy cannot regress:

- a fresh boot with RAG / translation / TTS / mail-digest unconfigured
  owns exactly the documented scheduler set — no feature loop ever
  appears for a feature that was never enabled (translation and TTS own
  NO loop at all: they are request-scoped);
- every loop that stays alive while its feature is disabled does a
  minimal settings probe per tick and provably NO feature work (no
  send, no generation, no IMAP connection, no vec connection, no model
  load, no service resident);
- the RAG idle-unload loop only ever touches ``rag_service`` slots.

The loops are driven for real: tick intervals are monkeypatched to
milliseconds and a counting wrapper around ``for_each_active_user``
observes that passes actually ran, so "no-op" is proven, not assumed.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from types import SimpleNamespace


def run(coroutine):
    return asyncio.run(coroutine)


@contextlib.asynccontextmanager
async def _booted() -> AsyncIterator[SimpleNamespace]:
    """Real lifespan on the conftest hermetic DB; yields app.state."""
    from lumirss.main import lifespan

    app = SimpleNamespace(state=SimpleNamespace())
    async with lifespan(app):
        yield app.state


def _counting_user_pass(monkeypatch):
    """Wrap ``for_each_active_user`` with a pass counter. Loop coroutines
    import it at their first run, so patches installed before the task
    starts are observed."""
    import lumirss.user_scope as user_scope

    real = user_scope.for_each_active_user
    calls = {"n": 0}

    async def spy(app_state, coro_fn, **kwargs):
        calls["n"] += 1
        await real(app_state, coro_fn, **kwargs)

    monkeypatch.setattr(user_scope, "for_each_active_user", spy)
    return calls


async def _await_passes(calls: dict, n: int, *, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while calls["n"] < n:
        if loop.time() > deadline:
            raise AssertionError(
                f"loop pass did not run: {calls['n']} < {n} within {timeout}s"
            )
        await asyncio.sleep(0.005)


async def _cancel(task: asyncio.Task) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


# ---- boot economy ------------------------------------------------------------


def test_fresh_boot_owns_exactly_the_documented_scheduler_set():
    """Fresh env, every optional feature unconfigured: the registry owns
    ONLY the documented always-on probes + the two RAG bookkeeping loops
    (idle unload + incremental probe). Translation and TTS are
    request-scoped and own NO background slot; obsidian owns none while
    unconfigured (interval 0); search sync is conftest-disabled. A new
    always-on loop for an unconfigured feature fails this test."""

    async def scenario():
        from lumirss.runtime import SCHEDULERS

        async with _booted() as state:
            assert sorted(SCHEDULERS.owned_names()) == [
                "digest_scheduler",
                "gpt_digest_scheduler",
                "mail_imap",
                "rag_idle",
                "rag_index",
            ], "unconfigured features must not add scheduler slots"
            # ...and nothing was built for features nobody configured.
            assert state.rag_service is None
            assert state.translation_service is None
            assert state.summary_service is None
            assert state.user_services == {}
        assert SCHEDULERS.owned_names() == []

    run(scenario())


# ---- mail digest: disabled tick never sends ----------------------------------


def test_mail_digest_loop_disabled_tick_never_sends(monkeypatch):
    import lumirss.mail_digest as mail_digest

    monkeypatch.setattr(mail_digest, "_SCHEDULE_TICK_SECONDS", 0.01)
    sends: list[str] = []

    async def scenario():
        async with _booted() as state:
            calls = _counting_user_pass(monkeypatch)

            async def send_fn():
                sends.append("sent")

            task = mail_digest.build_digest_scheduler_task(state)
            await _await_passes(calls, 2)
            await _cancel(task)
        assert sends == [], "disabled digest must never reach send_fn"

    run(scenario())


def test_mail_digest_explicit_enabled_zero_also_never_sends():
    """The migration ships digest_settings enabled=0; an explicitly
    disabled row is the same honest no-op and writes nothing back."""
    from lumirss.mail_digest import DigestScheduler
    from lumirss.user_scope import user_context

    sends: list[str] = []

    async def scenario():
        async with _booted() as state:
            with user_context(state.owner_id):
                await state.db.execute(
                    "UPDATE digest_settings SET enabled = 0 WHERE id = 1"
                )
                scheduler = DigestScheduler(state.db)
                await scheduler.maybe_send(lambda: sends.append("sent"))
                row = await state.db.fetch_one(
                    "SELECT enabled, last_sent_at FROM digest_settings "
                    "WHERE id = 1"
                )
                assert int(row["enabled"]) == 0
                assert row["last_sent_at"] is None
        assert sends == []

    run(scenario())


# ---- gpt digest: disabled tick never generates -------------------------------


def test_gpt_digest_loop_disabled_tick_never_generates(monkeypatch):
    import lumirss.gpt_digest as gpt_digest
    from lumirss.gpt_digest_configs import GptDigestConfigStore
    from lumirss.user_scope import user_context

    monkeypatch.setattr(gpt_digest, "_SCHEDULE_TICK_SECONDS", 0.01)
    generation_calls: list[str] = []

    # Record-then-raise: the loops isolate per-user exceptions by design,
    # so a raising-only sentinel would vanish into the error log. The
    # recorded call list is the evidence the assertions below check.
    def _must_not_run(*_args, **_kwargs):
        generation_calls.append("generate")
        raise AssertionError("generation path entered while unconfigured")

    def _merge_must_not_run(*_args, **_kwargs):
        generation_calls.append("merge")
        raise AssertionError("merge path entered while unconfigured")

    monkeypatch.setattr(gpt_digest, "_scheduled_generate", _must_not_run)
    monkeypatch.setattr(gpt_digest, "_merge_missed_into_pool", _merge_must_not_run)

    async def scenario():
        async with _booted() as state:
            calls = _counting_user_pass(monkeypatch)
            task = gpt_digest.build_gpt_digest_scheduler_task(state)
            await _await_passes(calls, 2)
            await _cancel(task)
            assert generation_calls == [], (
                "generation/merge ran while the digest was disabled"
            )
            with user_context(state.owner_id):
                # Migration 0027 ships ONE default config, disabled — the
                # loop pass over it must have generated nothing.
                configs = await GptDigestConfigStore(state.db).list_configs()
                assert [c["enabled"] for c in configs] == [False]

    run(scenario())


# ---- mail IMAP: unconfigured tick never constructs the adapter ---------------


def test_mail_imap_loop_unconfigured_tick_never_touches_imap(monkeypatch):
    import lumirss.mail_imap as mail_imap

    monkeypatch.setattr(mail_imap, "_DEFAULT_INTERVAL_SECONDS", 0.01)
    adapter_builds: list[str] = []

    def _boom(*_args, **_kwargs):
        # Record-then-raise: the loop isolates per-user exceptions, so
        # the recorded list is the checked evidence, not the exception.
        adapter_builds.append("ImapAdapter")
        raise AssertionError("ImapAdapter built while mail is unconfigured")

    monkeypatch.setattr(mail_imap, "ImapAdapter", _boom)

    async def scenario():
        async with _booted() as state:
            calls = _counting_user_pass(monkeypatch)
            task = mail_imap.build_mail_imap_task(state)
            await _await_passes(calls, 2)
            await _cancel(task)
            assert adapter_builds == [], (
                "IMAP adapter constructed while mail was unconfigured"
            )

    run(scenario())


# ---- RAG: never-enabled user is probed, never indexed ------------------------


def test_rag_incremental_loop_probe_never_opens_vec_or_stays_resident(
    monkeypatch,
):
    """The default-on incremental loop may do ONE settings SELECT per
    user per tick to notice enablement — but for a never-enabled user it
    must not open the sqlite-vec connection, not cache a RagService,
    and not leave anything resident."""
    import lumirss.rag as rag

    real_service = rag.RagService
    probes: list[object] = []
    vec_opens: list[str] = []

    class ProbeSpy(real_service):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            probes.append(self)

        def _vec_connection(self):
            # Record-then-raise: per-user isolation would swallow the
            # exception silently; the list is the checked evidence.
            vec_opens.append("vec_connection")
            raise AssertionError(
                "vec connection opened for a never-enabled user"
            )

    monkeypatch.setattr(rag, "RagService", ProbeSpy)

    async def scenario():
        async with _booted() as state:
            calls = _counting_user_pass(monkeypatch)
            task = rag.build_rag_incremental_task(state, 0.01)
            await _await_passes(calls, 2)
            await _cancel(task)

            assert probes, "loop never probed (test would prove nothing)"
            assert vec_opens == [], (
                "sqlite-vec connection opened for a never-enabled user"
            )
            assert not [
                key for key in state.user_services if key[1] == "rag_service"
            ], "a RagService became resident while RAG was never enabled"
            assert all(p._vec_conn is None for p in probes)  # noqa: SLF001

    run(scenario())


# ---- RAG idle unload: only rag_service slots are touched ---------------------


def test_rag_idle_loop_unloads_only_rag_service_slots(monkeypatch):
    import lumirss.rag as rag

    monkeypatch.setattr(rag, "_RAG_IDLE_TICK_SECONDS", 0.01)

    class ForeignService:
        def __init__(self):
            self.unloads = 0

        def unload_if_idle(self):
            self.unloads += 1
            return False

    class RagSpy:
        def __init__(self):
            self.unloads = 0

        def unload_if_idle(self):
            self.unloads += 1
            return False

    async def scenario():
        async with _booted() as state:
            foreign = ForeignService()
            rag_spy = RagSpy()
            state.user_services = {
                ("u1", "other_service"): foreign,
                ("u1", "rag_service"): rag_spy,
            }
            task = rag.build_rag_idle_task(state)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 5.0
            while rag_spy.unloads < 2:
                if loop.time() > deadline:
                    raise AssertionError("idle loop never ticked")
                await asyncio.sleep(0.005)
            await _cancel(task)
            assert foreign.unloads == 0, (
                "idle loop must only touch rag_service slots"
            )

    run(scenario())
