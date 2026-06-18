import logging

import pandas as pd
import streamlit as st

from api_client import APIError, clear_data, upload_file
from map_utils import MAP_HEIGHT, flatten_properties, make_preview_map

logger = logging.getLogger("geojson_dashboard.ui.upload")


def render_upload_tab() -> None:
    left, right = st.columns([1, 2], gap="large")
    _api_online = st.session_state.get("health_ok", True)

    with left:
        st.subheader("Upload GeoJSON")
        st.caption("Load Polygon or MultiPolygon features into the active API session.")

        if not _api_online:
            st.warning(
                "API is offline. Start the API service to upload files.",
                icon=":material/cloud_off:",
            )

        uploaded_file = st.file_uploader(
            "Choose a GeoJSON file",
            type=["geojson"],
            label_visibility="collapsed",
            disabled=not _api_online,
        )

        with st.container(horizontal=True):
            upload_btn = (
                st.button("Upload", type="primary", icon=":material/upload:")
                if uploaded_file is not None and _api_online
                else None
            )
            clear_btn = st.button("Clear session", icon=":material/delete_sweep:")

        if upload_btn and uploaded_file is not None:
            with st.spinner("Uploading…"):
                try:
                    result = upload_file(uploaded_file.getvalue(), uploaded_file.name)
                    st.session_state["upload_result"] = result
                    st.session_state["file_name"] = uploaded_file.name
                    st.session_state["features"] = (
                        result.get("processed_geojson", {}).get("features", [])
                    )
                    st.session_state["crs_status"] = result.get("crs")
                    st.session_state.pop("validate_result", None)
                    st.session_state.pop("duplicate_result", None)
                    st.session_state.pop("upload_focus_id", None)  # reset to full extent
                    st.session_state.pop("upload_feat_list", None)
                    st.session_state.pop("focus_feature_id", None)
                    st.session_state.pop("feat_list", None)
                    st.session_state.pop("_prev_visible_ids", None)
                    st.session_state.pop("edit_map_view", None)
                    n = len(st.session_state["features"])
                    logger.info("Uploaded %d feature(s) from '%s'", n, uploaded_file.name)
                    st.toast(
                        f"Uploaded {n} feature{'s' if n != 1 else ''} from **{uploaded_file.name}**",
                        icon=":material/check_circle:",
                    )
                    st.rerun()
                except APIError as exc:
                    logger.warning("Upload of '%s' failed: %s", uploaded_file.name, exc.message)
                    st.error(exc.message, icon=":material/error:")
                    if exc.errors:
                        st.dataframe(pd.DataFrame(exc.errors), hide_index=True)

        if clear_btn:
            clear_data()
            st.rerun()

        result = st.session_state.get("upload_result")
        if result:
            loaded = result.get("selected_features", 0)
            total = result.get("total_features", loaded)
            crs = result.get("crs") or {}
            if result.get("valid"):
                st.success(
                    f"All {loaded} feature{'s' if loaded != 1 else ''} accepted.",
                    icon=":material/check_circle:",
                )
            else:
                st.warning(
                    f"{loaded} of {total} features loaded — {total - loaded} skipped.",
                    icon=":material/warning:",
                )
                if result.get("errors"):
                    with st.expander("Skipped features", icon=":material/info:", expanded=False):
                        st.dataframe(pd.DataFrame(result["errors"]), hide_index=True)

            if crs.get("present"):
                if crs.get("accepted"):
                    st.success(
                        f"CRS accepted: {crs.get('name')}",
                        icon=":material/check_circle:",
                    )
                else:
                    st.warning(
                        "CRS key found, but it is not CRS84. The app assumes WGS84 lon/lat and does not reproject coordinates.",
                        icon=":material/travel_explore:",
                    )
                with st.expander("CRS value", icon=":material/data_object:", expanded=False):
                    st.json(crs.get("value"))
            else:
                st.info("No top-level CRS key found in the uploaded GeoJSON.", icon=":material/info:")

    with right:
        features = st.session_state.get("features", [])
        crs = st.session_state.get("crs_status")
        crs_ok = not crs or crs.get("accepted", True)

        if features and not crs_ok:
            st.info(
                "Map and attribute table are hidden until the CRS issue is resolved "
                "(see the warning on the left) — positions computed from this file "
                "would be unreliable.",
                icon=":material/public_off:",
            )
        elif features:
            prop_df = flatten_properties(features)
            n_up = len(prop_df)
            _focus = st.session_state.get("upload_focus_id")

            # Read the table's last known checked rows so the map, drawn
            # above the table, reflects the current visibility right away.
            _prior_sel = st.session_state.get("upload_feat_list")
            _prior_rows = (
                _prior_sel["selection"].get("rows", list(range(n_up)))
                if _prior_sel else list(range(n_up))
            )
            visible_ids = {int(prop_df.iloc[r]["#"]) for r in _prior_rows if r < n_up}

            st.pydeck_chart(
                make_preview_map(features, _focus, visible_ids),
                height=MAP_HEIGHT - 100,
                key=f"upload_map_{_focus}_{len(features)}",
            )

            _up_lbl, _up_zoom = st.columns([3, 0.7])
            _up_lbl.markdown("**Attribute table** — check a feature to show it on the map")
            if _up_zoom.button(
                ":material/zoom_in:", help="Zoom to checked feature(s)", width="stretch", key="upload_zoom_btn"
            ):
                st.session_state["upload_focus_id"] = sorted(visible_ids) or None
                st.rerun()

            st.dataframe(
                prop_df,
                hide_index=True,
                height=220,
                on_select="rerun",
                selection_mode="multi-row",
                selection_default={"selection": {"rows": list(range(n_up))}},
                key="upload_feat_list",
            )
        else:
            st.info(
                "Upload a GeoJSON file to see the map and attribute table here.",
                icon=":material/map:",
            )
