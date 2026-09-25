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

from lumirss.accounts_store import AccountsStore, hash_password  # noqa: E402
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
    # 0067 多账户：登录校验的是 users.password_hash（AccountsStore），
    # 旧 auth_password 表已不再喂登录——写 owner 行并落 password_updated_at。
    store = AccountsStore(database)
    owner = None
    for row in await store.list_users(limit=500):
        if row.get("role") == "owner":
            owner = row
            break
    if owner is None:
        raise SystemExit("owner account not found — migration did not run?")
    # set_password_hash 同时落 password_updated_at（store 内部 invariant）。
    await store.set_password_hash(str(owner["id"]), hash_password(password))
    print("password hash installed; all previous sessions revoked")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
