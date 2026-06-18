import logging

import pandas as pd
import streamlit as st

from api_client import APIError, api_request, refresh_features, require_api_connection, require_valid_crs

logger = logging.getLogger("geojson_dashboard.ui.duplicates")


def render_duplicate_tab(features: list[dict]) -> None:
    st.subheader("Duplicates and intersections")
    st.caption("Detect repeated geometries and groups of features that spatially intersect.")

    if not require_api_connection("retry_duplicate"):
        return

    if not require_valid_crs():
        return

    if not features:
        st.info("Upload a GeoJSON file first to scan for duplicates.", icon=":material/info:")
        return

    threshold = st.slider(
        "Duplicate match threshold",
        min_value=0.50,
        max_value=1.00,
        value=0.99,
        step=0.01,
        help="Higher values require closer coordinate matches to flag a duplicate.",
    )

    dup_result = st.session_state.get("duplicate_result")
    dup_count = (
        sum(1 for f in dup_result.get("features", []) if f.get("is_duplicate"))
        if dup_result else 0
    )

    with st.container(horizontal=True):
        scan_btn = st.button("Scan for duplicates", type="primary", icon=":material/search:")
        remove_btn = st.button("Remove duplicates", disabled=dup_count == 0, icon=":material/delete:")

    if scan_btn:
        with st.spinner("Scanning…"):
            try:
                st.session_state["duplicate_result"] = api_request(
                    "GET", "/duplicates",
                    params={"remove_duplicates": False, "duplicate_threshold": threshold},
                )
                logger.info("Duplicate scan run at threshold=%.2f", threshold)
                st.rerun()
            except APIError as exc:
                logger.warning("Duplicate scan failed: %s", exc.message)
                st.error(exc.message, icon=":material/error:")

    if remove_btn:
        with st.spinner("Removing duplicates…"):
            try:
                st.session_state["duplicate_result"] = api_request(
                    "GET", "/duplicates",
                    params={"remove_duplicates": True, "duplicate_threshold": threshold},
                )
                st.session_state.pop("focus_feature_id", None)
                st.session_state.pop("feat_list", None)
                st.session_state.pop("_prev_visible_ids", None)
                st.session_state.pop("edit_map_view", None)
                refresh_features()
                logger.info("Duplicates removed at threshold=%.2f", threshold)
                st.toast("Duplicate features removed.", icon=":material/check_circle:")
            except APIError as exc:
                logger.warning("Duplicate removal failed: %s", exc.message)
                st.error(exc.message, icon=":material/error:")

    dup_result = st.session_state.get("duplicate_result")
    if dup_result:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Duplicate groups", dup_result["duplicate_groups_found"])
        c2.metric("Duplicates", dup_count)
        c3.metric("Intersect groups", dup_result.get("intersect_groups_found", 0))
        c4.metric("Intersect pairs", dup_result.get("intersections_found", 0))

        rows = []
        for f in dup_result.get("features", []):
            fid = f["feature_id"]
            props = (
                dict(features[fid].get("properties") or {})
                if 0 <= fid < len(features) else {}
            )
            rows.append({
                "Feature":        fid,
                "Type":           f["geometry_type"],
                "Valid":          bool(f["geometry_valid"]),
                "Duplicate":      bool(f["is_duplicate"]),
                "Dup group":      f["duplicate_group"],
                "Intersects":     bool(f.get("has_intersection")),
                "Intersect group": f.get("intersect_group"),
                **props,
            })
        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            column_config={
                "Valid":      st.column_config.CheckboxColumn("Valid"),
                "Duplicate":  st.column_config.CheckboxColumn("Duplicate"),
                "Intersects": st.column_config.CheckboxColumn("Intersects"),
            },
        )

        pairs = dup_result.get("intersection_pairs", [])
        if pairs:
            with st.expander("Intersection pairs", icon=":material/info:", expanded=False):
                st.dataframe(pd.DataFrame(pairs), hide_index=True)
