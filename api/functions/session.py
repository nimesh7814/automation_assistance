from typing import Annotated
from fastapi import HTTPException, Header

# Per-session storage: maps session_id -> {"data": geojson | None}
_sessions: dict[str, dict] = {}


def get_session_id(x_session_id: Annotated[str | None, Header()] = None) -> str:
    if not x_session_id:
        raise HTTPException(status_code=400, detail="Missing X-Session-ID header.")
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
