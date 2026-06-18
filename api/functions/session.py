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


def check_feature_id(feature_id: int, features: list) -> None:
    """Raise 404 if feature_id is out of range. Shared by every route that
    targets a single feature by its list index (geometry/properties edit, delete)."""
    if feature_id < 0 or feature_id >= len(features):
        raise HTTPException(
            status_code=404,
            detail=f"Feature {feature_id} not found. Valid range is 0 to {len(features) - 1}.",
        )


def set_dataset(session_id: str, data: dict) -> None:
    _sessions.setdefault(session_id, {})["data"] = data


def set_crs_status(session_id: str, crs_status: dict | None) -> None:
    _sessions.setdefault(session_id, {})["crs"] = crs_status


def get_crs_status(session_id: str) -> dict | None:
    return _sessions.get(session_id, {}).get("crs")


def clear_geojson(session_id: str) -> dict:
    if session_id in _sessions:
        _sessions[session_id]["data"] = None
        _sessions[session_id]["crs"] = None
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
