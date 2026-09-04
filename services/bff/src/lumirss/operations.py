"""Operations status / readiness (0018).

Real dependency probing with failure isolation:

- lumi.sqlite is the CORE dependency: if it is unusable, readiness fails.
- FreshRSS down = reading/subscription management unavailable (existing
  semantics), but the BFF stays alive.
- RSSHub down = only source discovery / preview / new-feed generation are
  affected; already-fetched RSS reading keeps working. RSSHub is NEVER
  treated as a core dependency.

All returned messages are static, browser-safe strings — never raw
exceptions, never URLs carrying credentials.
"""

from datetime import datetime, timezone

import httpx
from pydantic import ValidationError

from lumirss.config import FreshRSSSettings, LumiSettings, RssHubSettings
from lumirss.migrations import schema_version
from lumirss.storage import Database, DatabaseError

_PROBE_TIMEOUT = httpx.Timeout(5.0, connect=3.0)

FRESHRSS_STATUSES = ("unconfigured", "healthy", "unauthenticated", "unavailable")
RSSHUB_STATUSES = ("unconfigured", "healthy", "unavailable")
SQLITE_STATUSES = ("healthy", "unavailable")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _status_entry(status: str, latency_ms: int | None, error: dict | None) -> dict:
    return {
        "status": status,
        "latencyMs": latency_ms,
        "lastCheckedAt": _utc_now(),
        "error": error,
    }


class OperationsService:
    """Bounded, redacted dependency probing over the shared HTTP client."""

    def __init__(self, client: httpx.AsyncClient, db: Database) -> None:
        self._client = client
        self._db = db

    async def sqlite_status(self) -> dict:
        """Core dependency: migrate() proves the DB opens and is current."""
        try:
            await self._db.migrate()
            version = await self._run_sync_schema_version()
        except DatabaseError:
            return _status_entry("unavailable", None, {"type": "database_error"})
        return {"status": "healthy", "schemaVersion": version}

    async def _run_sync_schema_version(self) -> int:
        import asyncio

        return await asyncio.to_thread(schema_version, self._db)

    async def freshrss_status(self) -> dict:
        """Probe FreshRSS with a single bounded ClientLogin attempt.

        ClientLogin proves reachability AND credential validity in one
        request: 200 -> healthy, 401 -> unauthenticated (reachable but bad
        credentials), timeout/connection -> unavailable. This is read-only
        and has no side effects.
        """
        try:
            settings = FreshRSSSettings()
        except ValidationError:
            return _status_entry("unconfigured", None, None)
        base = settings.FRESHRSS_BASE_URL.rstrip("/")
        url = f"{base}/api/greader.php/accounts/ClientLogin"
        started = datetime.now(timezone.utc)
        try:
            response = await self._client.post(
                url,
                data={
                    "Email": settings.FRESHRSS_USERNAME,
                    "Passwd": settings.FRESHRSS_API_PASSWORD.get_secret_value(),
                },
                timeout=_PROBE_TIMEOUT,
            )
        except httpx.HTTPError:
            return _status_entry("unavailable", None, {"type": "connection_error"})
        latency_ms = int(
            (datetime.now(timezone.utc) - started).total_seconds() * 1000
        )
        if response.status_code == 200:
            return _status_entry("healthy", latency_ms, None)
        if response.status_code == 401:
            return _status_entry(
                "unauthenticated",
                latency_ms,
                {"type": "authentication_error"},
            )
        return _status_entry(
            "unavailable",
            latency_ms,
            {"type": "upstream_error"},
        )

    async def rsshub_status(self) -> dict:
        """Probe RSSHub's /healthz (the same endpoint dev compose uses)."""
        try:
            settings = RssHubSettings()
        except ValidationError:
            return _status_entry("unconfigured", None, None)
        if not settings.RSSHUB_BASE_URL:
            return _status_entry("unconfigured", None, None)
        url = f"{settings.RSSHUB_BASE_URL.rstrip('/')}/healthz"
        started = datetime.now(timezone.utc)
        try:
            response = await self._client.get(url, timeout=_PROBE_TIMEOUT)
        except httpx.HTTPError:
            return _status_entry("unavailable", None, {"type": "connection_error"})
        latency_ms = int(
            (datetime.now(timezone.utc) - started).total_seconds() * 1000
        )
        if response.status_code == 200:
            return _status_entry("healthy", latency_ms, None)
        return _status_entry(
            "unavailable",
            latency_ms,
            {"type": "upstream_error"},
        )

    async def full_status(self) -> dict:
        """The operations view for the Web UI (redacted by construction)."""
        sqlite = await self.sqlite_status()
        freshrss = await self.freshrss_status()
        rsshub = await self.rsshub_status()
        return {
            "lumi": {"status": "healthy", "version": LumiSettings().LUMIRSS_VERSION},
            "sqlite": sqlite,
            "freshrss": {"configured": freshrss["status"] != "unconfigured", **freshrss},
            "rsshub": {"configured": rsshub["status"] != "unconfigured", **rsshub},
        }

    async def ready(self) -> tuple[bool, dict]:
        """Readiness: core dependency (lumi.sqlite) must be healthy.

        FreshRSS/RSSHub are reported but never fail readiness — that would
        violate the failure-isolation model (RSSHub down must not make
        already-fetched reading unavailable).
        """
        sqlite = await self.sqlite_status()
        ready = sqlite["status"] == "healthy"
        freshrss = await self.freshrss_status()
        rsshub = await self.rsshub_status()
        return ready, {
            "status": "ok" if ready else "unavailable",
            "components": {
                "lumi": {"status": "healthy"},
                "sqlite": sqlite,
                "freshrss": freshrss["status"],
                "rsshub": rsshub["status"],
            },
        }
