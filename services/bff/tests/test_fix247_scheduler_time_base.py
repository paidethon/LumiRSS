"""FIX-247 pinning: the periodic schedulers use one clear time base.

Persisted markers are UTC (``lumirss.util.utc_now``); scheduling
decisions compare wall-clock identity in the CONFIGURED timezone on
both sides (marker converted into the same zone). Consequences pinned
here against a doubled wall hour and a timezone switch:

- a DST fall-back (a wall hour that occurs twice) still sends exactly
  once — the second occurrence carries the same wall identity as the
  marker written by the first;
- changing the configured timezone after a send never produces a second
  send for the already-sent instant — the marker is UTC on disk, so the
  comparison re-projects BOTH sides into the new zone consistently.

ARCH-08 adds the cross-process window lease on top (scope = the wall
identity string); these tests pin the single-process semantics that
lease scopes are derived from.
"""

import asyncio
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from lumirss.mail_digest import DigestScheduler, DigestStore

_FALL_BACK_DAY = "America/New_York"  # 2026-11-01: 02:00 EDT -> 01:00 EST


def run(coroutine):
    return asyncio.run(coroutine)


def _store(client) -> DigestStore:
    from lumirss.main import app

    return DigestStore(
        app.state.db,
        app.state.secrets_store.store_for(app.state.owner_id),
    )


def test_dst_fall_back_repeated_wall_hour_sends_exactly_once(client):
    store = _store(client)
    run(store.save({"enabled": True, "hour": 1, "timezone": _FALL_BACK_DAY}))
    sent: list[str] = []

    first = datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo(_FALL_BACK_DAY), fold=0)
    second = datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo(_FALL_BACK_DAY), fold=1)
    # The two occurrences are distinct instants but the same wall hour.
    assert first.utcoffset() != second.utcoffset()
    assert first.strftime("%Y-%m-%dT%H") == second.strftime("%Y-%m-%dT%H")

    async def send(tag: str) -> None:
        # Production send path stamps last_sent_at in UTC (mark_sent).
        await store._db.execute(
            "UPDATE digest_settings SET last_sent_at = ? WHERE id = 1",
            (first.astimezone(UTC).isoformat(timespec="seconds"),),
        )
        sent.append(tag)

    scheduler = DigestScheduler(store._db, clock=lambda _tz: first)
    run(scheduler.maybe_send(lambda: send("first")))
    assert sent == ["first"]

    # Same wall hour, SECOND real instant (the repeated hour): no resend.
    scheduler2 = DigestScheduler(store._db, clock=lambda _tz: second)
    run(scheduler2.maybe_send(lambda: send("repeat")))
    assert sent == ["first"], "DST fall-back must not re-send the same wall hour"


def test_utc_marker_survives_timezone_switch_without_double_send(client):
    store = _store(client)
    run(store.save({"enabled": True, "hour": 8, "timezone": "Asia/Shanghai"}))
    sent: list[str] = []

    # Shanghai 08:00 = 00:00 UTC — the send happens and stamps UTC.
    shanghai_8 = datetime(2026, 3, 1, 8, 0, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert shanghai_8.astimezone(UTC).hour == 0

    async def send(tag: str) -> None:
        await store._db.execute(
            "UPDATE digest_settings SET last_sent_at = ? WHERE id = 1",
            (shanghai_8.astimezone(UTC).isoformat(timespec="seconds"),),
        )
        sent.append(tag)

    run(DigestScheduler(store._db, clock=lambda _tz: shanghai_8).maybe_send(lambda: send("sh")))
    assert sent == ["sh"]

    # Operator switches the config to UTC/hour=0 half an hour later: the
    # instant 00:30 UTC is the same wall identity the marker projects to
    # — no second send for the same window.
    run(store.save({"enabled": True, "hour": 0, "timezone": "UTC"}))
    utc_0030 = shanghai_8.astimezone(UTC).replace(minute=30)
    run(DigestScheduler(store._db, clock=lambda _tz: utc_0030).maybe_send(lambda: send("switch")))
    assert sent == ["sh"], "UTC-persisted marker must dedupe across a timezone switch"
