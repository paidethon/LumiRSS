"""LumiRSS BFF application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from lumirss.adapters.freshrss import (
    AuthenticationError,
    ConfigError,
    FreshRSSAdapter,
    UpstreamConnectionError,
    UpstreamError,
)
from lumirss.config import FreshRSSSettings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create the shared HTTP client; the FreshRSSAdapter is created lazily
    on the first /api/v1/feeds request (so /health/live works even when
    FreshRSS is not configured)."""
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=5.0),
        trust_env=False,
    )
    app.state.freshrss_adapter = None
    yield
    await app.state.http_client.aclose()


app = FastAPI(title="LumiRSS BFF", lifespan=lifespan)


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    """Liveness: only proves this process is alive, never touches FreshRSS."""
    return {"status": "ok"}


_ERROR_RESPONSES = {
    ConfigError: (503, "configuration_error"),
    AuthenticationError: (502, "authentication_error"),
    UpstreamConnectionError: (502, "connection_error"),
    UpstreamError: (502, "upstream_error"),
}


@app.exception_handler(ConfigError)
@app.exception_handler(AuthenticationError)
@app.exception_handler(UpstreamConnectionError)
@app.exception_handler(UpstreamError)
async def adapter_error_handler(request: Request, exc: Exception) -> JSONResponse:
    status, error_type = _ERROR_RESPONSES[type(exc)]
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": str(exc)}},
    )


@app.get("/api/v1/feeds")
async def feeds(request: Request) -> list[dict[str, str]]:
    """List feeds from FreshRSS through the FreshRSSAdapter.

    The adapter is created lazily on the first request (settings are only
    read/validated here, never at startup) and then cached on app.state so
    later requests reuse it and its in-memory auth token.
    """
    adapter = request.app.state.freshrss_adapter
    if adapter is None:
        try:
            settings = FreshRSSSettings()
        except ValidationError as exc:
            raise ConfigError(
                "FreshRSS settings are missing or invalid. "
                "Set FRESHRSS_BASE_URL / FRESHRSS_USERNAME / FRESHRSS_API_PASSWORD."
            ) from exc
        adapter = FreshRSSAdapter(request.app.state.http_client, settings)
        request.app.state.freshrss_adapter = adapter
    feeds = await adapter.list_feeds()
    return [{"title": feed.title, "feedUrl": feed.feed_url} for feed in feeds]
