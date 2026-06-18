import logging

import streamlit as st

from api_client import APIError, api_request, require_api_connection, require_valid_crs
from map_utils import flatten_properties

logger = logging.getLogger("geojson_dashboard.ui.export")


def render_export_tab(features: list[dict]) -> None:
    st.subheader("Export")
    st.caption("Download the current session as a GeoJSON file after validation, cleanup, or edits.")

    if not require_api_connection("retry_export"):
        return

    if not require_valid_crs():
        return

    if not features:
        st.info("Upload data before exporting.", icon=":material/info:")
        return

    st.markdown("**Current features**")
    st.dataframe(flatten_properties(features), hide_index=True)

    st.markdown("")

    export_bytes = st.session_state.get("export_bytes")
    if export_bytes:
        # Green download button (styled via CSS rule for stDownloadButton)
        st.download_button(
            "Download GeoJSON",
            data=export_bytes,
            file_name="cleaned_geojson.geojson",
            mime="application/geo+json",
            icon=":material/download:",
        )
    else:
        if st.button("Download GeoJSON", icon=":material/download:", type="primary"):
            with st.spinner("Building export file…"):
                try:
                    st.session_state["export_bytes"] = api_request("GET", "/export", raw=True)
                    logger.info("Export built for %d feature(s)", len(features))
                    st.toast("Ready — click Download GeoJSON to save.", icon=":material/check_circle:")
                    st.rerun()
                except APIError as exc:
                    logger.warning("Export failed: %s", exc.message)
                    st.error(exc.message, icon=":material/error:")
