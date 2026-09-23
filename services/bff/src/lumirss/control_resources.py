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


_MAX_SOURCE_RESULTS_ERROR_CHARS = 200


async def apply_scheme_initial_sources(state, user_id: str, source_urls: list[str]) -> list[dict[str, object]]:
    """Best-effort subscription of an invite scheme's initial sources (N001).

    Called right after a scheme-stamped activation: every URL is
    attempted once through the new user's own FreshRSS binding. Failures
    are listed honestly per URL (bounded message, no credentials) and
    NEVER block or roll back the activation — an account is usable with
    a pending source list. Requires a complete FreshRSS binding; when
    binding is still pending every URL reports that state.
    """
    results: list[dict[str, object]] = []
    adapter = await user_freshrss_adapter(state, user_id)
    if adapter is None:
        return [{"url": url, "ok": False, "error": "freshrss_binding_pending"} for url in source_urls]
    from lumirss.adapters.freshrss_control import FreshRSSControlAdapter

    control = FreshRSSControlAdapter(adapter)
    for url in source_urls:
        try:
            await control.subscribe(url)
            results.append({"url": url, "ok": True, "error": None})
        except Exception as exc:  # noqa: BLE001 — best-effort by contract
            results.append({"url": url, "ok": False, "error": str(exc)[:_MAX_SOURCE_RESULTS_ERROR_CHARS]})
    return results
