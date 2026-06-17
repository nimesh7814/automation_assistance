import logging

import pandas as pd
import streamlit as st

from api_client import APIError, api_request, refresh_features, require_api_connection

logger = logging.getLogger("geojson_dashboard.ui.validate")


def render_validate_tab(features: list[dict]) -> None:
    st.subheader("Geometry validation")
    st.caption("Find invalid rings, winding problems, self-intersections, and hole placement issues.")

    if not require_api_connection("retry_validate"):
        return

    if not features:
        st.info("Upload a GeoJSON file first to run validation.", icon=":material/info:")
        return

    with st.container(horizontal=True):
        validate_btn = st.button("Validate", type="primary", icon=":material/search:")
        fix_btn = st.button("Fix auto-fixable", icon=":material/build:")

    if validate_btn:
        with st.spinner("Validating geometries…"):
            try:
                st.session_state["validate_result"] = api_request("GET", "/validate")
                # Clear old fix result so it doesn't show stale data alongside fresh validate
                st.session_state.pop("fix_result", None)
                logger.info("Validation run on %d feature(s)", len(features))
            except APIError as exc:
                logger.warning("Validation failed: %s", exc.message)
                st.error(exc.message, icon=":material/error:")

    if fix_btn:
        with st.spinner("Applying fixes…"):
            try:
                st.session_state["fix_result"] = api_request("POST", "/fix")
                refresh_features()
                logger.info("Auto-fix applied")
                st.toast("Auto-fixable issues resolved.", icon=":material/check_circle:")
            except APIError as exc:
                logger.warning("Auto-fix failed: %s", exc.message)
                st.error(exc.message, icon=":material/error:")

    result = st.session_state.get("validate_result")
    if result:
        summary = result["summary"]
        cols = st.columns(4)
        cols[0].metric("Status", "Valid" if result["is_valid"] else "Issues found")
        cols[1].metric("Issues", summary["invalid_count"])
        cols[2].metric("Features", summary["total_features"])
        cols[3].metric("Geometry types", ", ".join(summary["geometry_types"].keys()) or "—")

        issues = result.get("issues", [])
        if issues:
            df = pd.DataFrame(issues)
            df["auto_fixable"] = df["auto_fixable"].map({True: "Yes", False: "No"})
            st.dataframe(df, hide_index=True)
        else:
            st.success("No geometry issues found.", icon=":material/check_circle:")

    fix_result = st.session_state.get("fix_result")
    if fix_result:
        with st.container(border=True):
            st.markdown("**Fix result**")
            fc, rc = st.columns(2)
            fc.metric("Fixed", fix_result["summary"]["fixed_count"])
            rc.metric("Remaining", fix_result["summary"]["remaining_count"])
            if fix_result.get("remaining"):
                st.dataframe(pd.DataFrame(fix_result["remaining"]), hide_index=True)
