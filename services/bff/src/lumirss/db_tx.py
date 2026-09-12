"""Multi-statement atomic writes over the Lumi Database (phase2 recovery).

``Database.execute`` commits every statement — correct for single writes,
but multi-row invariants (library_items + library_clips + the search
projection, asset rows + identity rows) need one atomic commit or the
crash/abort window leaves permanent orphans (P0-03/P0-04). storage.py
does not expose a transaction primitive, so this module provides the
missing piece locally: one connection, N statements, one commit, full
rollback on any failure. The sync block runs in a worker thread like
every other Database call so async routes never block the event loop.

House SQL rules still apply inside ``fn``: single-line inline literals
with bound ``?`` params, no f-string/format SQL, no UPSERT syntax
(explicit SELECT-then-INSERT/UPDATE instead).

If storage.py later grows a public ``transaction()`` contextmanager,
this module becomes a thin alias (requested in the recovery report).
"""

import asyncio
import sqlite3
from collections.abc import Callable

from lumirss.storage import Database


def _run_in_transaction[T](db: Database, fn: Callable[[sqlite3.Connection], T]) -> T:
    # ``_connect`` is the Database's own connection factory (WAL, foreign
    # keys, busy timeout); it is the only supported way to share one
    # connection across several statements.
    connection = db._connect()
    try:
        result = fn(connection)
        connection.commit()
        return result
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


async def transaction[T](
    db: Database, fn: Callable[[sqlite3.Connection], T]
) -> T:
    """Run ``fn(conn)`` atomically: one connection, one commit.

    ``fn`` runs synchronously on a worker thread and receives a raw
    ``sqlite3.Connection``. sqlite3.IntegrityError propagates unchanged
    so callers can implement converge-on-duplicate semantics; every
    other sqlite3.Error surfaces as-is for the error envelope.
    """
    return await asyncio.to_thread(_run_in_transaction, db, fn)
