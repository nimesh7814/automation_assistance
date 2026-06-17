import json
import logging

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from api_client import APIError, api_request, refresh_features, require_api_connection
from map_utils import (
    MAP_HEIGHT,
    _drawing_to_geometry,
    _geometries_equal,
    flatten_properties,
    make_edit_map,
    update_map_bounds,
)

logger = logging.getLogger("geojson_dashboard.ui.edit")


def _save_single_feature_attrs(feature_id: int, row: pd.Series) -> bool:
    """Save one feature's attributes. Returns True on success."""
    payload = {}
    for key, value in row.to_dict().items():
        try:
            payload[key] = None if pd.isna(value) else value
        except (TypeError, ValueError):
            payload[key] = value
    try:
        api_request("PUT", f"/features/{feature_id}/properties", json=payload)
        logger.info("Attributes saved for feature %d", feature_id)
        return True
    except APIError as exc:
        logger.warning("Saving attributes for feature %d failed: %s", feature_id, exc.message)
        st.error(exc.message, icon=":material/error:")
        return False


def add_attribute_column(features: list[dict], column_name: str, default_value: str) -> None:
    errors = []
    for fid, feature in enumerate(features):
        props = dict(feature.get("properties") or {})
        props.setdefault(column_name, default_value)
        try:
            api_request("PUT", f"/features/{fid}/properties", json=props)
        except APIError as exc:
            errors.append({"feature": fid, "error": exc.message})

    if errors:
        logger.warning("Adding column '%s' failed for %d feature(s)", column_name, len(errors))
        st.error("The column could not be added to every feature.", icon=":material/error:")
        st.dataframe(pd.DataFrame(errors), hide_index=True)
        return

    refresh_features()
    logger.info("Column '%s' added to %d feature(s)", column_name, len(features))
    st.toast(f"Column '{column_name}' added.", icon=":material/check_circle:")
    st.rerun()


def render_edit_tab(features: list[dict]) -> None:
    st.subheader("Edit features")
    st.caption(
        "Check a feature to show it on the map — all features are shown by default. "
        "Click a row to edit its attributes. Use the zoom button to focus the map on it."
    )

    if not require_api_connection("retry_edit"):
        return

    if not features:
        st.info("Upload data before editing.", icon=":material/info:")
        return

    df = flatten_properties(features)
    n = len(df)

    # Restore last selection (persists across reruns)
    stored = int(st.session_state.get("focus_feature_id", 0) or 0)
    stored = max(0, min(stored, n - 1))

    # Apply any pending checkbox-state change requested on the previous run -
    # must happen before the "feat_list" widget below is instantiated.
    pending_rows = st.session_state.pop("_pending_feat_rows", None)
    if pending_rows is not None:
        st.session_state["feat_list"] = {"selection": {"rows": pending_rows}}

    left, right = st.columns([1.4, 1], gap="large")

    with right:
        # Table 1: feature list. The checkbox shows/hides on the map; clicking
        # a row also makes it the active feature for the attributes panel.
        _z_lbl, _z_btn, _z_del = st.columns([3, 0.7, 0.7])
        _z_lbl.markdown("**Feature list**")
        if _z_btn.button(":material/zoom_in:", help="Zoom to selected feature", width="stretch", key="zoom_btn"):
            st.session_state["edit_map_view"] = update_map_bounds(features, stored)
            st.rerun()
        with _z_del:
            st.markdown('<span class="del-feat-mark"></span>', unsafe_allow_html=True)
            if st.button("", icon=":material/delete:", help=f"Delete feature {stored}", width="stretch", key="del_feat_btn"):
                try:
                    api_request("DELETE", f"/features/{stored}")
                    st.session_state.pop("focus_feature_id", None)
                    st.session_state.pop("export_bytes", None)
                    st.session_state.pop("feat_list", None)
                    st.session_state.pop("_prev_visible_ids", None)
                    refresh_features()
                    logger.info("Feature %d deleted", stored)
                    st.toast(f"Feature {stored} deleted.", icon=":material/check_circle:")
                    st.rerun()
                except APIError as exc:
                    logger.warning("Deleting feature %d failed: %s", stored, exc.message)
                    st.error(exc.message, icon=":material/error:")

        sel_event = st.dataframe(
            df,
            hide_index=True,
            on_select="rerun",
            selection_mode="multi-row",
            selection_default={"selection": {"rows": list(range(n))}},
            key="feat_list",
            height=220,
        )

        sel_rows = sel_event.selection.rows if sel_event else list(range(n))
        visible_ids = {int(df.iloc[r]["#"]) for r in sel_rows if r < n}

        # The most recently *checked* row becomes the active feature for the
        # attributes panel below - unchecking a row only hides it on the map.
        prev_visible_ids = st.session_state.get("_prev_visible_ids")
        if prev_visible_ids is None:
            prev_visible_ids = set(visible_ids)
        newly_checked = visible_ids - prev_visible_ids
        st.session_state["_prev_visible_ids"] = visible_ids
        if newly_checked:
            stored = max(newly_checked)
            st.session_state["focus_feature_id"] = stored

        selected = stored

        # Table 2: editable attributes for the selected feature.
        st.markdown(f"**Attributes — Feature {selected}**")
        single_row = df[df["#"] == selected].set_index("#")
        edited = st.data_editor(
            single_row,
            hide_index=False,
            num_rows="fixed",
            key=f"attr_edit_{selected}",
        )

        with st.container(horizontal=True):
            save_btn = st.button("Save attributes", type="primary", icon=":material/save:")
            refresh_btn = st.button("Refresh", icon=":material/refresh:")

        if save_btn:
            for fid, row in edited.iterrows():
                if _save_single_feature_attrs(int(fid), row):
                    refresh_features()
                    st.toast(f"Feature {fid} attributes saved.", icon=":material/check_circle:")
                    st.rerun()

        if refresh_btn:
            refresh_features(show_errors=True)
            st.rerun()

        with st.expander("Add attribute column", icon=":material/add_column_right:", expanded=False):
            col_name = st.text_input("Column name", key="new_col_name")
            col_default = st.text_input("Default value", value="", key="new_col_default")
            if st.button("Add column", icon=":material/add:", disabled=not col_name.strip()):
                add_attribute_column(features, col_name.strip(), col_default)

        with st.expander("Edit geometry as JSON", icon=":material/code:", expanded=False):
            st.caption("Directly paste or edit a GeoJSON geometry object for the selected feature.")
            geom_text = json.dumps(features[selected].get("geometry"), indent=2)
            new_geom = st.text_area(
                "Geometry (GeoJSON)", geom_text, height=180, key=f"geom_json_{selected}"
            )
            if st.button("Save geometry JSON", icon=":material/save:", key="save_geom_json"):
                try:
                    payload = json.loads(new_geom)
                    api_request("PUT", f"/features/{selected}/geometry", json={"geometry": payload})
                    refresh_features()
                    logger.info("Geometry JSON saved for feature %d", selected)
                    st.toast(f"Geometry saved for feature {selected}.", icon=":material/check_circle:")
                    st.rerun()
                except json.JSONDecodeError as exc:
                    st.error(f"Invalid JSON: {exc}", icon=":material/error:")
                except APIError as exc:
                    logger.warning("Saving geometry JSON for feature %d failed: %s", selected, exc.message)
                    st.error(exc.message, icon=":material/error:")

    with left:
        st.markdown("**Map** — :blue[blue] = selected · :green[green] = others")
        st.caption(
            "Draw a polygon to add it as a new feature. To reshape an existing feature, "
            "select it, drag its vertices with the pencil (edit) tool, then click the "
            "checkmark — the change saves automatically."
        )

        # Pan/zoom is separate, persistent state - it only changes when the
        # zoom or full-extent buttons are pressed, never on mere selection.
        if "edit_map_view" not in st.session_state:
            st.session_state["edit_map_view"] = update_map_bounds(features, selected)
        view = st.session_state["edit_map_view"]

        map_result = st_folium(
            make_edit_map(features, selected, view, visible_ids),
            height=MAP_HEIGHT,
            width=None,
            returned_objects=["last_active_drawing", "all_drawings"],
            zoom=view["zoom"],
            center=(view["latitude"], view["longitude"]),
            key="edit_map",
        )

        all_drawings = (map_result or {}).get("all_drawings") or []
        n_drawings = len(all_drawings)

        baseline_geom = features[selected].get("geometry") or {}
        has_baseline = bool(baseline_geom.get("coordinates"))
        n_baseline = 1 if has_baseline else 0

        # Per-(selected feature, feature count) counter so each new map starts clean
        _map_inst = f"_ndraw_{selected}_{len(features)}"
        n_processed = st.session_state.get(_map_inst, n_baseline)

        if n_drawings > n_processed:
            # A brand-new polygon was drawn beyond the preloaded one - create a new feature
            st.session_state[_map_inst] = n_drawings
            new_geom = _drawing_to_geometry(all_drawings[-1])
            if new_geom:
                new_id = len(features)
                try:
                    api_request(
                        "POST", "/features",
                        json={"type": "Feature", "properties": {}, "geometry": new_geom},
                    )
                    st.session_state["focus_feature_id"] = new_id
                    st.session_state.pop("export_bytes", None)
                    rows = sorted(visible_ids | {new_id})
                    st.session_state["_pending_feat_rows"] = rows
                    st.session_state["_prev_visible_ids"] = set(rows)
                    refresh_features()
                    logger.info("Feature %d created by drawing", new_id)
                    st.toast(
                        f"Feature {new_id} created — enter attributes below.",
                        icon=":material/check_circle:",
                    )
                    st.rerun()
                except APIError as exc:
                    logger.warning("Creating feature from drawing failed: %s", exc.message)
                    st.error(exc.message, icon=":material/error:")
        elif has_baseline and n_drawings == n_baseline:
            # The preloaded feature's vertices may have been edited in place
            edited_geom = _drawing_to_geometry(all_drawings[0]) if all_drawings else None
            if edited_geom and not _geometries_equal(edited_geom, baseline_geom):
                try:
                    api_request("PUT", f"/features/{selected}/geometry", json={"geometry": edited_geom})
                    refresh_features()
                    st.session_state[_map_inst] = n_drawings
                    logger.info("Geometry updated for feature %d via map edit", selected)
                    st.toast(f"Geometry updated for feature {selected}.", icon=":material/check_circle:")
                    st.rerun()
                except APIError as exc:
                    logger.warning("Updating geometry for feature %d failed: %s", selected, exc.message)
                    st.error(exc.message, icon=":material/error:")

        if st.button("Full extent", icon=":material/fit_screen:", help="Zoom out to show all features."):
            st.session_state["edit_map_view"] = update_map_bounds(features, None)
            st.rerun()
