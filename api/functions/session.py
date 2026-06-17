import asyncio
import logging
import os
import time
from typing import Annotated

from fastapi import HTTPException, Header

logger = logging.getLogger("geojson_dashboard.session")

# Per-session storage: maps session_id -> {"data": geojson | None, "last_access": float}
_sessions: dict[str, dict] = {}

SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_MINUTES", "30")) * 60
_SWEEP_INTERVAL_SECONDS = 60


def get_session_id(x_session_id: Annotated[str | None, Header()] = None) -> str:
    if not x_session_id:
        raise HTTPException(status_code=400, detail="Missing X-Session-ID header.")
    session = _sessions.setdefault(x_session_id, {"data": None})
    session["last_access"] = time.monotonic()
    return x_session_id


def get_dataset(session_id: str) -> dict:
    data = _sessions.get(session_id, {}).get("data")
    if data is None:
        raise HTTPException(status_code=404, detail="No GeoJSON data in session. Upload first.")
    return data


def set_dataset(session_id: str, data: dict) -> None:
    _sessions.setdefault(session_id, {})["data"] = data


def clear_geojson(session_id: str) -> dict:
    if session_id in _sessions:
        _sessions[session_id]["data"] = None
    return {"message": "Session data cleared."}


async def sweep_idle_sessions() -> None:
    """Background loop: drop sessions that haven't made any API call (any
    request through get_session_id) in SESSION_TTL_SECONDS, freeing their
    cached GeoJSON data."""
    while True:
        await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
        now = time.monotonic()
        expired = [
            sid for sid, session in _sessions.items()
            if now - session.get("last_access", now) > SESSION_TTL_SECONDS
        ]
        for sid in expired:
            del _sessions[sid]
        if expired:
            logger.info(
                "Expired %d idle session(s) after %d minute(s) of inactivity",
                len(expired), SESSION_TTL_SECONDS // 60,
            )
