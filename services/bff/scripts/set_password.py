"""set_password.py — one-shot bootstrap for session authentication.

Run INSIDE the BFF container (via `./lumirss set-password` on the host).
The new password arrives through a runtime secret channel only:

- piped on stdin, or
- provided via the environment variable LUMIRSS_NEW_PASSWORD.

The plaintext is never an argv (never visible in `ps`), never persisted,
never logged. This script writes ONLY the bcrypt hash into lumi.sqlite
(auth_password). Re-running replaces the hash and revokes every
existing session.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))

from lumirss.auth_store import AuthStore  # noqa: E402
from lumirss.config import LumiSettings  # noqa: E402
from lumirss.storage import Database  # noqa: E402


def _read_password() -> str:
    env_password = os.environ.get("LUMIRSS_NEW_PASSWORD", "")
    if env_password:
        return env_password
    from_stdin = sys.stdin.read()
    if not from_stdin:
        raise SystemExit(
            "no password provided — pipe it on stdin or export it as LUMIRSS_NEW_PASSWORD"
        )
    return from_stdin.rstrip("\n")


async def main() -> int:
    password = _read_password()
    settings = LumiSettings()
    database = Database(settings.LUMIRSS_DB_PATH)
    await database.migrate()
    await AuthStore(database).set_password(password)
    print("password hash installed; all previous sessions revoked")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
