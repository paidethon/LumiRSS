"""Control-plane resource helpers (0067).

Operations that write into a user's namespace from the control plane —
invitation activation, pool binding, background-task adapter builds —
with the user context entered explicitly (never via request state).
Kept out of the routers so the auth flow, admin tooling and background
loops share one implementation.
"""

from lumirss.user_scope import user_context


async def bind_freshrss_account(state, user_id: str, freshrss_username: str, base_url: str, public_url: str = "", source: str = "pool") -> None:
    """Write a user's FreshRSS binding row + API password secret.

    The password is read from the control secrets file (pool registration
    key) and copied into the USER's secrets file; the control copy stays
    so a failed binding can be re-attempted without re-provisioning.
    """
    control_secrets = state.control_secrets
    password = control_secrets.get(f"freshrss_pool:{freshrss_username}")
    if not password:
        raise LookupError("Pool account password missing — re-register the pool entry.")
    with user_context(user_id):
        await state.db.migrate()
        await state.db.execute("INSERT OR REPLACE INTO freshrss_binding (id, base_url, username, public_url, bound_at, source) VALUES (1, ?, ?, ?, strftime('%s','now'), ?)", (base_url, freshrss_username, public_url, source))
        state.secrets_store.set("freshrss_api_password", password)


async def user_freshrss_adapter(state, user_id: str):
    """Build (or reuse) the per-user FreshRSSAdapter for background work.

    Returns None when the user has no complete binding — background
    passes skip that user honestly instead of using shared credentials.
    """
    from lumirss.adapters.freshrss import FreshRSSAdapter
    from lumirss.config import FreshRSSSettings

    cache_key = (user_id, "bg_freshrss_adapter")
    cached = state.user_services.get(cache_key)
    if cached is not None:
        return cached
    with user_context(user_id):
        await state.db.migrate()
        row = await state.db.fetch_one("SELECT base_url, username, public_url FROM freshrss_binding WHERE id = 1")
        if row is None:
            return None
        password = state.secrets_store.get("freshrss_api_password")
        if not password:
            return None
        from pydantic import SecretStr

        settings = FreshRSSSettings(
            FRESHRSS_BASE_URL=str(row["base_url"]),
            FRESHRSS_USERNAME=str(row["username"]),
            FRESHRSS_PUBLIC_URL=str(row["public_url"] or ""),
            FRESHRSS_API_PASSWORD=SecretStr(password),
        )
        adapter = FreshRSSAdapter(state.http_client, settings)
    state.user_services[cache_key] = adapter
    return adapter
