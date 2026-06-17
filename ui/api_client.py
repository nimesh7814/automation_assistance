import logging
import os
import time
import uuid
from typing import Any

import requests
import streamlit as st

logger = logging.getLogger("geojson_dashboard.ui.api")

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")


class APIError(Exception):
    def __init__(self, message: str, errors: list | None = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.errors = errors or []
        self.status_code = status_code


def init_session() -> None:
    """Persist the session ID in the URL so a browser refresh restores it."""
    if "session_id" in st.query_params:
        st.session_state["session_id"] = st.query_params["session_id"]
    elif "session_id" not in st.session_state:
        sid = str(uuid.uuid4())
        st.session_state["session_id"] = sid
        st.query_params["session_id"] = sid


def session_headers() -> dict[str, str]:
    return {"X-Session-ID": st.session_state["session_id"]}


def api_request(method: str, path: str, raw: bool = False, **kwargs) -> Any:
    try:
        response = requests.request(
            method,
            f"{API_BASE_URL}{path}",
            headers={**session_headers(), **kwargs.pop("headers", {})},
            timeout=30,
            **kwargs,
        )
    except requests.RequestException as exc:
        logger.warning("%s %s -> connection failed: %s", method, path, exc)
        raise APIError(f"Cannot reach the API at {API_BASE_URL}.") from exc

    if response.status_code >= 400:
        try:
            payload = response.json()
        except ValueError:
            payload = {"message": response.text or "Request failed.", "errors": []}
        logger.warning("%s %s -> %d %s", method, path, response.status_code, payload.get("message", ""))
        raise APIError(
            payload.get("message", "Request failed."),
            payload.get("errors", []),
            response.status_code,
        )

    logger.info("%s %s -> %d", method, path, response.status_code)

    if raw:
        return response.content

    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        return response.json()
    return response.content


def upload_file(file_bytes: bytes, filename: str) -> dict:
    return api_request(
        "POST",
        "/upload/file",
        files={"file": (filename, file_bytes, "application/geo+json")},
    )


def probe_health() -> bool:
    """Check GET / for {"message": "API Connected"} - cached 15s to avoid hammering."""
    now = time.monotonic()
    if now - st.session_state.get("_health_ts", 0) < 15:
        return st.session_state.get("health_ok", False)
    try:
        result = api_request("GET", "/")
        ok = isinstance(result, dict) and result.get("message") == "API Connected"
    except APIError:
        ok = False
    st.session_state["health_ok"] = ok
    st.session_state["_health_ts"] = now
    return ok


def refresh_features(show_errors: bool = False) -> list[dict]:
    try:
        result = api_request("GET", "/features")
        features = result.get("features", [])
        st.session_state["features"] = features
        st.session_state["api_ok"] = True
        return features
    except APIError as exc:
        st.session_state["features"] = []
        st.session_state["api_ok"] = False
        if show_errors and exc.status_code != 404:
            st.error(exc.message, icon=":material/error:")
        return []


def clear_data() -> None:
    try:
        api_request("DELETE", "/data")
    except APIError:
        pass
    for key in [
        "features",
        "upload_result",
        "validate_result",
        "fix_result",
        "duplicate_result",
        "export_bytes",
        "file_name",
        "focus_feature_id",
        "ai_messages",
        "ai_sent_count",
        "feat_list",
        "_prev_visible_ids",
        "edit_map_view",
        "upload_focus_id",
        "upload_feat_list",
    ]:
        st.session_state.pop(key, None)
    # Fresh session ID embedded in the URL so the next refresh starts clean
    # rather than trying to restore the just-deleted session.
    new_sid = str(uuid.uuid4())
    st.session_state["session_id"] = new_sid
    st.query_params["session_id"] = new_sid
    logger.info("Session cleared, new session_id=%s", new_sid)


def require_api_connection(key: str = "retry_api") -> bool:
    """Show offline banner + retry button; return True only when API is reachable."""
    if st.session_state.get("health_ok", True):
        return True
    st.error(
        "**Backend not connected.** The API is unreachable — start the API service and retry.",
        icon=":material/cloud_off:",
    )
    if st.button("Retry connection", icon=":material/refresh:", key=key):
        st.session_state.pop("_health_ts", None)
        st.rerun()
    return False
