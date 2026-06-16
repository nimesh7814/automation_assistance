import json
import os
import uuid
from typing import Any

import pandas as pd
import pydeck as pdk
import requests
import streamlit as st
from folium import FeatureGroup, GeoJson, GeoJsonTooltip, Map, Polygon
from folium.plugins import Draw
from streamlit_folium import st_folium


API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
MAP_HEIGHT = 560


class APIError(Exception):
    def __init__(self, message: str, errors: list | None = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.errors = errors or []
        self.status_code = status_code


def session_headers() -> dict[str, str]:
    if "session_id" not in st.session_state:
        st.session_state["session_id"] = str(uuid.uuid4())
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
        raise APIError(f"Cannot reach the API at {API_BASE_URL}.") from exc

    if response.status_code >= 400:
        try:
            payload = response.json()
        except ValueError:
            payload = {"message": response.text or "Request failed.", "errors": []}
        raise APIError(
            payload.get("message", "Request failed."),
            payload.get("errors", []),
            response.status_code,
        )

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


def refresh_features(show_errors: bool = False) -> list[dict]:
    try:
        result = api_request("GET", "/features")
        features = result.get("features", [])
        st.session_state["features"] = features
        return features
    except APIError as exc:
        st.session_state["features"] = []
        if show_errors and exc.status_code != 404:
            st.error(exc.message)
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
    ]:
        st.session_state.pop(key, None)


def flatten_properties(features: list[dict]) -> pd.DataFrame:
    rows = []
    all_keys = sorted({
        key
        for feature in features
        for key in (feature.get("properties") or {}).keys()
    })
    for index, feature in enumerate(features):
        props = feature.get("properties") or {}
        rows.append({"Feature": index, **{key: props.get(key) for key in all_keys}})
    return pd.DataFrame(rows)


def collect_geometry_points(geometry: dict) -> list[list[float]]:
    points = []

    def collect_coords(value):
        if not isinstance(value, list):
            return
        if len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
            points.append(value[:2])
            return
        for item in value:
            collect_coords(item)

    collect_coords((geometry or {}).get("coordinates"))
    return points


def update_map_bounds(features: list[dict], focus_feature_id: int | None = None) -> dict:
    points = []

    if focus_feature_id is not None and 0 <= focus_feature_id < len(features):
        points = collect_geometry_points(features[focus_feature_id].get("geometry") or {})

    if not points:
        for feature in features:
            points.extend(collect_geometry_points(feature.get("geometry") or {}))

    if not points:
        return {"latitude": 0, "longitude": 0, "zoom": 1}

    lon_values = [point[0] for point in points]
    lat_values = [point[1] for point in points]
    min_lon, max_lon = min(lon_values), max(lon_values)
    min_lat, max_lat = min(lat_values), max(lat_values)
    span = max(max_lon - min_lon, max_lat - min_lat)
    zoom = 15 if span < 0.01 else 12 if span < 0.05 else 9 if span < 0.5 else 5

    return {
        "latitude": (min_lat + max_lat) / 2,
        "longitude": (min_lon + max_lon) / 2,
        "zoom": zoom,
    }


def make_map(
    features: list[dict],
    color_by: str | None = None,
    focus_feature_id: int | None = None,
) -> pdk.Deck:
    view_state = pdk.ViewState(**update_map_bounds(features, focus_feature_id), pitch=0)
    rendered_features = []

    palette = [
        [30, 104, 175, 150],
        [232, 120, 73, 150],
        [65, 148, 108, 150],
        [164, 93, 176, 150],
        [210, 151, 55, 150],
        [77, 152, 163, 150],
    ]
    categories: dict[str, list[int]] = {}

    for index, feature in enumerate(features):
        item = dict(feature)
        properties = dict(item.get("properties") or {})
        properties["_feature_id"] = index
        if color_by and color_by in properties:
            category = str(properties.get(color_by))
            if category not in categories:
                categories[category] = palette[len(categories) % len(palette)]
            properties["_fill_color"] = categories[category]
        else:
            properties["_fill_color"] = palette[index % len(palette)]
        item["properties"] = properties
        rendered_features.append(item)

    layer = pdk.Layer(
        "GeoJsonLayer",
        {"type": "FeatureCollection", "features": rendered_features},
        pickable=True,
        stroked=True,
        filled=True,
        get_fill_color="properties._fill_color",
        get_line_color=[36, 45, 57, 220],
        get_line_width=2,
        line_width_min_pixels=1,
    )

    return pdk.Deck(
        map_style=None,
        initial_view_state=view_state,
        layers=[layer],
        tooltip={
            "html": "<b>Feature {properties._feature_id}</b><br/>{properties}",
            "style": {"backgroundColor": "#17202a", "color": "white"},
        },
    )


def render_status_bar(features: list[dict]) -> None:
    upload_result = st.session_state.get("upload_result") or {}
    selected = upload_result.get("selected_features", len(features))
    total = upload_result.get("total_features", len(features))
    source = st.session_state.get("file_name", "No file loaded")

    cols = st.columns([1.2, 1, 1, 1])
    cols[0].metric("Source", source)
    cols[1].metric("Loaded", selected)
    cols[2].metric("Skipped", max(total - selected, 0))
    cols[3].metric("Session", st.session_state["session_id"][:8])


def render_upload_tab() -> None:
    left, right = st.columns([1.05, 1.95], gap="large")

    with left:
        st.subheader("Upload GeoJSON")
        st.caption("Load Polygon or MultiPolygon features into the active API session.")
        uploaded_file = st.file_uploader(
            "Choose a GeoJSON file",
            type=["geojson", "json"],
            label_visibility="collapsed",
        )

        actions = st.columns(2)
        if uploaded_file is not None and actions[0].button("Upload", type="primary", width="stretch"):
            try:
                result = upload_file(uploaded_file.getvalue(), uploaded_file.name)
                st.session_state["upload_result"] = result
                st.session_state["file_name"] = uploaded_file.name
                st.session_state["features"] = result.get("processed_geojson", {}).get("features", [])
                st.session_state.pop("validate_result", None)
                st.session_state.pop("duplicate_result", None)
                st.success("File uploaded.")
            except APIError as exc:
                st.error(exc.message)
                if exc.errors:
                    st.dataframe(pd.DataFrame(exc.errors), width="stretch", hide_index=True)

        if actions[1].button("Clear", width="stretch"):
            clear_data()
            st.rerun()

        result = st.session_state.get("upload_result")
        if result:
            if result.get("valid"):
                st.success("All features were accepted.")
            else:
                st.warning("Some features were skipped.")
                if result.get("errors"):
                    with st.expander("Skipped features", expanded=False):
                        st.dataframe(pd.DataFrame(result["errors"]), width="stretch", hide_index=True)

    with right:
        features = st.session_state.get("features", [])
        st.subheader("Map preview")
        if features:
            property_df = flatten_properties(features)
            color_options = [None] + [column for column in property_df.columns if column != "Feature"]
            color_by = st.selectbox(
                "Color by",
                color_options,
                format_func=lambda value: "Feature order" if value is None else str(value),
            )
            st.pydeck_chart(make_map(features, color_by), height=MAP_HEIGHT)
        else:
            st.info("Upload a GeoJSON file to preview it on the map.")


def geometry_to_leaflet_layers(geometry: dict) -> list[list[list[float]]]:
    if not geometry:
        return []

    if geometry.get("type") == "Polygon":
        return [[coord[1], coord[0]] for coord in geometry.get("coordinates", [[]])[0]]

    if geometry.get("type") == "MultiPolygon":
        layers = []
        for polygon in geometry.get("coordinates", []):
            if polygon:
                layers.append([[coord[1], coord[0]] for coord in polygon[0]])
        return layers

    return []


def leaflet_feature_to_geometry(drawing: dict) -> dict | None:
    geometry = (drawing or {}).get("geometry")
    if not isinstance(geometry, dict):
        return None
    if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        return None
    return geometry


def make_edit_map(features: list[dict], selected_id: int) -> Map:
    bounds = update_map_bounds(features, selected_id)
    fmap = Map(
        location=[bounds["latitude"], bounds["longitude"]],
        zoom_start=bounds["zoom"],
        control_scale=True,
        tiles="OpenStreetMap",
    )

    collection = {"type": "FeatureCollection", "features": []}
    for index, feature in enumerate(features):
        item = dict(feature)
        props = dict(item.get("properties") or {})
        props["feature_id"] = index
        item["properties"] = props
        collection["features"].append(item)

    GeoJson(
        collection,
        name="Features",
        tooltip=GeoJsonTooltip(fields=["feature_id"], aliases=["Feature"]),
        style_function=lambda feature: {
            "fillColor": "#2563eb" if feature["properties"]["feature_id"] == selected_id else "#22c55e",
            "color": "#111827" if feature["properties"]["feature_id"] == selected_id else "#334155",
            "weight": 3 if feature["properties"]["feature_id"] == selected_id else 1,
            "fillOpacity": 0.35 if feature["properties"]["feature_id"] == selected_id else 0.18,
        },
        highlight_function=lambda _feature: {"weight": 4, "fillOpacity": 0.45},
    ).add_to(fmap)

    editable_group = FeatureGroup(name="Editable copy").add_to(fmap)
    selected_geometry = features[selected_id].get("geometry") or {}
    selected_layers = geometry_to_leaflet_layers(selected_geometry)
    if selected_geometry.get("type") == "Polygon" and selected_layers:
        Polygon(
            locations=selected_layers,
            color="#dc2626",
            weight=3,
            fill=True,
            fill_opacity=0.15,
        ).add_to(editable_group)
    elif selected_geometry.get("type") == "MultiPolygon":
        for layer in selected_layers:
            Polygon(
                locations=layer,
                color="#dc2626",
                weight=3,
                fill=True,
                fill_opacity=0.15,
            ).add_to(editable_group)

    Draw(
        export=False,
        position="topleft",
        draw_options={
            "polyline": False,
            "rectangle": True,
            "circle": False,
            "circlemarker": False,
            "marker": False,
            "polygon": {
                "allowIntersection": True,
                "showArea": True,
                "shapeOptions": {"color": "#dc2626", "fillOpacity": 0.15},
            },
        },
        edit_options={"edit": True, "remove": False},
    ).add_to(fmap)

    return fmap


def render_validate_tab(features: list[dict]) -> None:
    st.subheader("Geometry validation")
    st.caption("Find invalid rings, winding problems, self-intersections, and hole placement issues.")

    controls = st.columns([1, 1, 3])
    if controls[0].button("Validate", type="primary", width="stretch", disabled=not features):
        try:
            st.session_state["validate_result"] = api_request("GET", "/validate")
        except APIError as exc:
            st.error(exc.message)

    if controls[1].button("Fix auto-fixable", width="stretch", disabled=not features):
        try:
            st.session_state["fix_result"] = api_request("POST", "/fix")
            refresh_features()
        except APIError as exc:
            st.error(exc.message)

    result = st.session_state.get("validate_result")
    if result:
        summary = result["summary"]
        cols = st.columns(4)
        cols[0].metric("Status", "Valid" if result["is_valid"] else "Issues found")
        cols[1].metric("Invalid issues", summary["invalid_count"])
        cols[2].metric("Features", summary["total_features"])
        cols[3].metric("Geometry types", ", ".join(summary["geometry_types"].keys()) or "-")

        issues = result.get("issues", [])
        if issues:
            df = pd.DataFrame(issues)
            df["auto_fixable"] = df["auto_fixable"].map({True: "Yes", False: "No"})
            st.dataframe(df, width="stretch", hide_index=True)
        else:
            st.success("No geometry issues were found.")

    fix_result = st.session_state.get("fix_result")
    if fix_result:
        st.divider()
        st.markdown("#### Last fix result")
        cols = st.columns(2)
        cols[0].metric("Fixed", fix_result["summary"]["fixed_count"])
        cols[1].metric("Remaining", fix_result["summary"]["remaining_count"])
        if fix_result.get("remaining"):
            st.dataframe(pd.DataFrame(fix_result["remaining"]), width="stretch", hide_index=True)


def render_duplicate_tab(features: list[dict]) -> None:
    st.subheader("Duplicates and intersections")
    st.caption("Detect repeated geometries and groups of features that spatially intersect.")

    threshold = st.slider(
        "Duplicate match threshold",
        min_value=0.50,
        max_value=1.00,
        value=0.99,
        step=0.01,
        help="Higher values compare more coordinate decimals.",
    )

    controls = st.columns([1, 1, 3])
    if controls[0].button("Scan", type="primary", width="stretch", disabled=not features):
        try:
            st.session_state["duplicate_result"] = api_request(
                "GET",
                "/duplicates",
                params={"remove_duplicates": False, "duplicate_threshold": threshold},
            )
        except APIError as exc:
            st.error(exc.message)

    duplicate_result = st.session_state.get("duplicate_result")
    duplicate_count = (
        sum(1 for feature in duplicate_result.get("features", []) if feature.get("is_duplicate"))
        if duplicate_result
        else 0
    )
    if controls[1].button("Remove duplicates", width="stretch", disabled=duplicate_count == 0):
        try:
            st.session_state["duplicate_result"] = api_request(
                "GET",
                "/duplicates",
                params={"remove_duplicates": True, "duplicate_threshold": threshold},
            )
            refresh_features()
        except APIError as exc:
            st.error(exc.message)

    if duplicate_result:
        cols = st.columns(4)
        cols[0].metric("Duplicate groups", duplicate_result["duplicate_groups_found"])
        cols[1].metric("Duplicates", duplicate_count)
        cols[2].metric("Intersect groups", duplicate_result.get("intersect_groups_found", 0))
        cols[3].metric("Intersect pairs", duplicate_result.get("intersections_found", 0))

        rows = []
        for feature in duplicate_result.get("features", []):
            rows.append({
                "Feature": feature["feature_id"],
                "Type": feature["geometry_type"],
                "Valid geometry": bool(feature["geometry_valid"]),
                "Duplicate": bool(feature["is_duplicate"]),
                "Duplicate group": feature["duplicate_group"],
                "Intersects": bool(feature.get("has_intersection")),
                "Intersect group": feature.get("intersect_group"),
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

        pairs = duplicate_result.get("intersection_pairs", [])
        if pairs:
            with st.expander("Intersection pairs", expanded=False):
                st.dataframe(pd.DataFrame(pairs), width="stretch", hide_index=True)


def save_attribute_table(edited: pd.DataFrame) -> None:
    errors = []
    for feature_id, row in edited.iterrows():
        payload = {
            key: None if pd.isna(value) else value
            for key, value in row.to_dict().items()
        }
        try:
            api_request("PUT", f"/features/{int(feature_id)}/properties", json=payload)
        except APIError as exc:
            errors.append({"feature": int(feature_id), "error": exc.message})

    if errors:
        st.error("Some rows could not be saved.")
        st.dataframe(pd.DataFrame(errors), width="stretch", hide_index=True)
        return

    refresh_features()
    st.success("Attribute table saved.")


def add_attribute_column(features: list[dict], column_name: str, default_value: str) -> None:
    errors = []
    for feature_id, feature in enumerate(features):
        properties = dict(feature.get("properties") or {})
        properties.setdefault(column_name, default_value)
        try:
            api_request("PUT", f"/features/{feature_id}/properties", json=properties)
        except APIError as exc:
            errors.append({"feature": feature_id, "error": exc.message})

    if errors:
        st.error("The column could not be added to every feature.")
        st.dataframe(pd.DataFrame(errors), width="stretch", hide_index=True)
        return

    refresh_features()
    st.success(f"Added column '{column_name}'.")
    st.rerun()


def render_edit_tab(features: list[dict]) -> None:
    st.subheader("Edit map and attributes")
    st.caption("Zoom to features, update attributes, add columns, and replace geometries from the map.")

    if not features:
        st.info("Upload data before editing.")
        return

    df = flatten_properties(features)
    if df.empty:
        st.info("No editable properties were found.")
        return

    selected_default = int(st.session_state.get("focus_feature_id", 0) or 0)
    selected_default = max(0, min(selected_default, len(features) - 1))

    left, right = st.columns([1.4, 1], gap="large")

    with right:
        st.markdown("#### Attribute table")
        table_event = st.dataframe(
            df,
            width="stretch",
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="attribute_focus_table",
        )
        selected_rows = table_event.selection.rows if table_event else []
        if selected_rows:
            st.session_state["focus_feature_id"] = int(df.iloc[selected_rows[0]]["Feature"])
            selected_default = st.session_state["focus_feature_id"]

        selected = st.number_input(
            "Selected feature",
            min_value=0,
            max_value=len(features) - 1,
            value=selected_default,
            step=1,
        )
        if st.button("Zoom to selected", width="stretch"):
            st.session_state["focus_feature_id"] = int(selected)
            st.rerun()

        edited = st.data_editor(
            df.set_index("Feature"),
            width="stretch",
            num_rows="fixed",
            key="property_editor",
        )

        table_actions = st.columns(2)
        if table_actions[0].button("Save table", type="primary", width="stretch"):
            save_attribute_table(edited)

        if table_actions[1].button("Refresh", width="stretch"):
            refresh_features(show_errors=True)
            st.rerun()

        with st.expander("Add attribute column", expanded=False):
            column_name = st.text_input("Column name")
            default_value = st.text_input("Default value", value="")
            if st.button("Add column", width="stretch", disabled=not column_name.strip()):
                add_attribute_column(features, column_name.strip(), default_value)

    with left:
        st.markdown("#### Editable map")
        st.caption(
            "Click a feature to inspect it. Use the draw toolbar to create or edit a polygon, "
            "then save the latest drawing to the selected feature."
        )
        map_result = st_folium(
            make_edit_map(features, int(selected)),
            height=MAP_HEIGHT,
            width=None,
            use_container_width=True,
            returned_objects=["last_active_drawing", "all_drawings", "last_object_clicked"],
            key=f"edit_map_{int(selected)}_{len(features)}",
        )

        clicked = map_result.get("last_object_clicked") if map_result else None
        if clicked:
            st.caption(f"Clicked at {clicked.get('lat'):.6f}, {clicked.get('lng'):.6f}")

        drawing = None
        drawings = map_result.get("all_drawings") if map_result else None
        if drawings:
            drawing = drawings[-1]
        elif map_result and map_result.get("last_active_drawing"):
            drawing = map_result["last_active_drawing"]

        map_actions = st.columns(3)
        if map_actions[0].button("Save drawing to selected", type="primary", width="stretch"):
            geometry = leaflet_feature_to_geometry(drawing)
            if geometry is None:
                st.error("Draw or edit a polygon on the map before saving.")
            else:
                try:
                    api_request("PUT", f"/features/{int(selected)}/geometry", json={"geometry": geometry})
                    refresh_features()
                    st.success(f"Geometry saved for feature {int(selected)}.")
                    st.rerun()
                except APIError as exc:
                    st.error(exc.message)

        if map_actions[1].button("Add drawing as feature", width="stretch"):
            geometry = leaflet_feature_to_geometry(drawing)
            if geometry is None:
                st.error("Draw a polygon on the map before adding a feature.")
            else:
                try:
                    api_request(
                        "POST",
                        "/features",
                        json={"type": "Feature", "properties": {}, "geometry": geometry},
                    )
                    refresh_features()
                    st.success("New feature added.")
                    st.rerun()
                except APIError as exc:
                    st.error(exc.message)

        if map_actions[2].button("Use full extent", width="stretch"):
            st.session_state.pop("focus_feature_id", None)
            st.rerun()

        with st.expander("Geometry JSON", expanded=False):
            geometry_text = json.dumps(features[int(selected)].get("geometry"), indent=2)
            new_geometry = st.text_area("Selected geometry", geometry_text, height=220)
            if st.button("Save geometry JSON", width="stretch"):
                try:
                    payload = json.loads(new_geometry)
                    api_request("PUT", f"/features/{int(selected)}/geometry", json={"geometry": payload})
                    refresh_features()
                    st.success("Geometry saved.")
                    st.rerun()
                except json.JSONDecodeError as exc:
                    st.error(f"Invalid JSON: {exc}")
                except APIError as exc:
                    st.error(exc.message)


def render_export_tab(features: list[dict]) -> None:
    st.subheader("Export")
    st.caption("Download the current session as GeoJSON after validation, cleanup, or edits.")

    if not features:
        st.info("Upload data before exporting.")
        return

    cols = st.columns([1, 1, 3])
    if cols[0].button("Prepare export", type="primary", width="stretch"):
        try:
            st.session_state["export_bytes"] = api_request("GET", "/export", raw=True)
        except APIError as exc:
            st.error(exc.message)

    export_bytes = st.session_state.get("export_bytes")
    if export_bytes:
        cols[1].download_button(
            "Download GeoJSON",
            data=export_bytes,
            file_name="cleaned_geojson.geojson",
            mime="application/geo+json",
            width="stretch",
        )

    st.markdown("#### Current features")
    st.dataframe(flatten_properties(features), width="stretch", hide_index=True)


st.set_page_config(page_title="GeoJSON Viewer", layout="wide")

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1rem;
        max-width: 1500px;
    }
    div[data-testid="stMetric"] {
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 0.75rem;
        background: #ffffff;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("GeoJSON Viewer")
st.caption("Import, validate, inspect, edit, and export farm polygons through the API backend.")

if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())

top_actions = st.columns([1, 1, 4])
if top_actions[0].button("Refresh data", width="stretch"):
    refresh_features(show_errors=True)
if top_actions[1].button("Clear session", width="stretch"):
    clear_data()
    st.rerun()

features = st.session_state.get("features")
if features is None:
    features = refresh_features()

render_status_bar(features)

tabs = st.tabs(["Upload", "Validate", "Duplicate", "Edit", "Export"])

with tabs[0]:
    render_upload_tab()

features = st.session_state.get("features", [])
with tabs[1]:
    render_validate_tab(features)

features = st.session_state.get("features", [])
with tabs[2]:
    render_duplicate_tab(features)

features = st.session_state.get("features", [])
with tabs[3]:
    render_edit_tab(features)

features = st.session_state.get("features", [])
with tabs[4]:
    render_export_tab(features)
