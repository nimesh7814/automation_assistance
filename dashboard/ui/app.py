import json
import os
import time
import uuid
from typing import Any

import pandas as pd
import pydeck as pdk
import requests
import streamlit as st
from dotenv import load_dotenv
from folium import GeoJson, GeoJsonTooltip, MacroElement, Map
from folium.plugins import Draw
from jinja2 import Template
from streamlit_folium import st_folium

from assistant import render_assistant_tab

# Loads GEMINI_API_KEY (and any other local overrides) from ui/.env when
# running the UI directly; in Docker these are already set via env_file.
load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
MAP_HEIGHT = 520


# ─── Exceptions ───────────────────────────────────────────────────────────────

class APIError(Exception):
    def __init__(self, message: str, errors: list | None = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.errors = errors or []
        self.status_code = status_code


# ─── Folium helper: pre-load geometry into Draw layer for vertex editing ──────

class _PreloadGeometry(MacroElement):
    """Injects a GeoJSON feature into the Leaflet Draw plugin's editable layer.

    This makes the selected feature's polygon immediately editable (vertex dragging)
    via the Draw toolbar's edit mode — without requiring the user to redraw it.
    """
    _template = Template("""
        {% macro script(this, kwargs) %}
        (function () {
            var data  = {{ this.geojson }};
            var geom  = data.geometry;
            if (!geom || !geom.coordinates) { return; }
            var opts  = {color: '#dc2626', weight: 2, fillOpacity: 0.15};
            function rings(polyCords) {
                return polyCords.map(function (ring) {
                    return ring.map(function (c) { return [c[1], c[0]]; });
                });
            }
            if (geom.type === 'Polygon') {
                L.polygon(rings(geom.coordinates), opts).addTo({{ this.var_name }});
            } else if (geom.type === 'MultiPolygon') {
                geom.coordinates.forEach(function (poly) {
                    L.polygon(rings(poly), opts).addTo({{ this.var_name }});
                });
            }
        })();
        {% endmacro %}
    """)

    def __init__(self, drawn_items_var: str, geometry: dict):
        super().__init__()
        self.var_name = drawn_items_var
        self.geojson = json.dumps({"type": "Feature", "geometry": geometry, "properties": {}})


# ─── API helpers ──────────────────────────────────────────────────────────────

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


def probe_health() -> bool:
    """Check GET / for {"message": "API Connected"} — cached 15 s to avoid hammering."""
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
    ]:
        st.session_state.pop(key, None)
    # Issue a fresh session ID and embed it in the URL so the next refresh
    # starts clean rather than trying to restore the just-deleted session.
    new_sid = str(uuid.uuid4())
    st.session_state["session_id"] = new_sid
    st.query_params["session_id"] = new_sid


# ─── Data helpers ─────────────────────────────────────────────────────────────

def flatten_properties(features: list[dict]) -> pd.DataFrame:
    rows = []
    all_keys = sorted({
        key
        for feature in features
        for key in (feature.get("properties") or {}).keys()
    })
    for index, feature in enumerate(features):
        props = feature.get("properties") or {}
        rows.append({"#": index, **{key: props.get(key) for key in all_keys}})
    return pd.DataFrame(rows)


def collect_geometry_points(geometry: dict) -> list[list[float]]:
    points = []

    def _collect(value):
        if not isinstance(value, list):
            return
        if len(value) >= 2 and all(isinstance(v, (int, float)) for v in value[:2]):
            points.append(value[:2])
            return
        for item in value:
            _collect(item)

    _collect((geometry or {}).get("coordinates"))
    return points


def update_map_bounds(features: list[dict], focus_id: int | None = None) -> dict:
    points = []
    if focus_id is not None and 0 <= focus_id < len(features):
        points = collect_geometry_points(features[focus_id].get("geometry") or {})
    if not points:
        for f in features:
            points.extend(collect_geometry_points(f.get("geometry") or {}))
    if not points:
        return {"latitude": 0, "longitude": 0, "zoom": 1}

    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    span = max(max(lons) - min(lons), max(lats) - min(lats))
    zoom = 15 if span < 0.01 else 12 if span < 0.05 else 9 if span < 0.5 else 5
    return {
        "latitude": (min(lats) + max(lats)) / 2,
        "longitude": (min(lons) + max(lons)) / 2,
        "zoom": zoom,
    }


# ─── Symbology ────────────────────────────────────────────────────────────────

_DEFAULT_SYMBOLOGY: dict = {
    "fill_color":      "#3b82f6",
    "stroke_color":    "#1e3a5f",
    "fill_opacity":    0.35,
    "stroke_width":    2,
    "color_by":        None,
    "category_colors": {},
}


def get_symbology() -> dict:
    return {**_DEFAULT_SYMBOLOGY, **st.session_state.get("symbology", {})}


def hex_to_rgba(hex_color: str, opacity: float = 1.0) -> list[int]:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return [r, g, b, int(opacity * 255)]


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


# ─── Map builders ─────────────────────────────────────────────────────────────

_PALETTE = [
    [30, 104, 175],
    [232, 120, 73],
    [65, 148, 108],
    [164, 93, 176],
    [210, 151, 55],
    [77, 152, 163],
]


def _palette_hex(idx: int) -> str:
    r, g, b = _PALETTE[idx % len(_PALETTE)]
    return f"#{r:02x}{g:02x}{b:02x}"


def make_preview_map(features: list[dict], focus_id: int | None = None) -> pdk.Deck:
    sym = get_symbology()
    color_by = sym.get("color_by")
    cat_colors = sym.get("category_colors") or {}
    opacity = sym["fill_opacity"]
    base_fill = hex_to_rgba(sym["fill_color"], opacity)
    view = pdk.ViewState(**update_map_bounds(features, focus_id), pitch=0)
    seen_cats: list[str] = []
    rendered = []

    for i, feature in enumerate(features):
        item = dict(feature)
        props = dict(item.get("properties") or {})
        props["_id"] = i
        if color_by and color_by in props:
            cat = str(props[color_by])
            if cat in cat_colors:
                props["_fill"] = hex_to_rgba(cat_colors[cat], opacity)
            else:
                if cat not in seen_cats:
                    seen_cats.append(cat)
                pal = _PALETTE[seen_cats.index(cat) % len(_PALETTE)]
                props["_fill"] = [pal[0], pal[1], pal[2], int(opacity * 255)]
        else:
            props["_fill"] = base_fill
        item["properties"] = props
        rendered.append(item)

    layer = pdk.Layer(
        "GeoJsonLayer",
        {"type": "FeatureCollection", "features": rendered},
        pickable=True,
        stroked=True,
        filled=True,
        get_fill_color="properties._fill",
        get_line_color=hex_to_rgba(sym["stroke_color"]),
        get_line_width=sym["stroke_width"],
        line_width_min_pixels=1,
    )
    return pdk.Deck(
        map_style=None,
        initial_view_state=view,
        layers=[layer],
        tooltip={
            "html": "<b>Feature {properties._id}</b><br/>{properties}",
            "style": {"backgroundColor": "#17202a", "color": "white"},
        },
    )


def _drawing_to_geometry(drawing: dict | None) -> dict | None:
    geometry = (drawing or {}).get("geometry")
    if not isinstance(geometry, dict):
        return None
    if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        return None
    return geometry


def make_edit_map(features: list[dict], selected_id: int) -> Map:
    sym = get_symbology()
    bounds = update_map_bounds(features, selected_id)
    fmap = Map(
        location=[bounds["latitude"], bounds["longitude"]],
        zoom_start=bounds["zoom"],
        control_scale=True,
        tiles="OpenStreetMap",
    )

    # Reference layer: selected = blue (fixed), others = user symbology
    collection = {"type": "FeatureCollection", "features": []}
    for i, f in enumerate(features):
        item = dict(f)
        props = dict(item.get("properties") or {})
        props["feature_id"] = i
        item["properties"] = props
        collection["features"].append(item)

    def _edit_style(feature, _sym=sym, _sel=selected_id):
        fid = feature["properties"]["feature_id"]
        if fid == _sel:
            return {"fillColor": "#2563eb", "color": "#111827", "weight": 3, "fillOpacity": 0.30}
        fill = _sym["fill_color"]
        cb = _sym.get("color_by")
        if cb and cb in feature["properties"]:
            fill = (_sym.get("category_colors") or {}).get(str(feature["properties"][cb]), fill)
        return {
            "fillColor": fill,
            "color": _sym["stroke_color"],
            "weight": _sym["stroke_width"],
            "fillOpacity": _sym["fill_opacity"],
        }

    GeoJson(
        collection,
        name="Features",
        tooltip=GeoJsonTooltip(fields=["feature_id"], aliases=["Feature"]),
        style_function=_edit_style,
        highlight_function=lambda _: {"weight": 4, "fillOpacity": 0.50},
    ).add_to(fmap)

    # Draw tool — edit_options make the toolbar show an edit (pencil) button
    draw = Draw(
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
                "shapeOptions": {"color": "#dc2626", "weight": 2, "fillOpacity": 0.15},
            },
        },
        edit_options={"edit": True, "remove": True},
    )
    draw.add_to(fmap)

    # Pre-load the selected feature's geometry into the Draw layer so the user
    # can immediately edit its vertices without having to redraw it.
    selected_geom = features[selected_id].get("geometry") or {}
    if selected_geom.get("coordinates"):
        drawn_items_var = f"drawnItems_{draw.get_name()}"
        _PreloadGeometry(drawn_items_var, selected_geom).add_to(fmap)

    return fmap


# ─── Tab renderers ────────────────────────────────────────────────────────────

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
                    st.session_state.pop("validate_result", None)
                    st.session_state.pop("duplicate_result", None)
                    st.session_state.pop("upload_focus_id", None)  # reset to full extent
                    n = len(st.session_state["features"])
                    st.toast(
                        f"Uploaded {n} feature{'s' if n != 1 else ''} from **{uploaded_file.name}**",
                        icon=":material/check_circle:",
                    )
                    st.rerun()
                except APIError as exc:
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

    with right:
        features = st.session_state.get("features", [])
        if features:
            prop_df = flatten_properties(features)
            _focus = st.session_state.get("upload_focus_id")
            st.pydeck_chart(
                make_preview_map(features, _focus),
                height=MAP_HEIGHT - 100,
                key=f"upload_map_{_focus}_{len(features)}",
            )
            st.markdown("**Attribute table** — click a row to zoom the map to that feature")
            _up_sel = st.dataframe(
                prop_df,
                hide_index=True,
                height=220,
                on_select="rerun",
                selection_mode="single-row",
                key="upload_feat_list",
            )
            _up_rows = _up_sel.selection.rows if _up_sel else []
            if _up_rows:
                _new_focus = int(prop_df.iloc[_up_rows[0]]["#"])
                if _new_focus != _focus:
                    st.session_state["upload_focus_id"] = _new_focus
                    st.rerun()
        else:
            st.info(
                "Upload a GeoJSON file to see the map and attribute table here.",
                icon=":material/map:",
            )


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
            except APIError as exc:
                st.error(exc.message, icon=":material/error:")

    if fix_btn:
        with st.spinner("Applying fixes…"):
            try:
                st.session_state["fix_result"] = api_request("POST", "/fix")
                refresh_features()
                st.toast("Auto-fixable issues resolved.", icon=":material/check_circle:")
            except APIError as exc:
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


def render_duplicate_tab(features: list[dict]) -> None:
    st.subheader("Duplicates and intersections")
    st.caption("Detect repeated geometries and groups of features that spatially intersect.")

    if not require_api_connection("retry_duplicate"):
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
                st.rerun()
            except APIError as exc:
                st.error(exc.message, icon=":material/error:")

    if remove_btn:
        with st.spinner("Removing duplicates…"):
            try:
                st.session_state["duplicate_result"] = api_request(
                    "GET", "/duplicates",
                    params={"remove_duplicates": True, "duplicate_threshold": threshold},
                )
                refresh_features()
                st.toast("Duplicate features removed.", icon=":material/check_circle:")
            except APIError as exc:
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
        return True
    except APIError as exc:
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
        st.error("The column could not be added to every feature.", icon=":material/error:")
        st.dataframe(pd.DataFrame(errors), hide_index=True)
        return

    refresh_features()
    st.toast(f"Column '{column_name}' added.", icon=":material/check_circle:")
    st.rerun()


def render_edit_tab(features: list[dict]) -> None:
    st.subheader("Edit features")
    st.caption(
        "Click a row in the feature list to focus the map on that feature. "
        "Edit its attributes below, or use the draw toolbar on the map to reshape the polygon."
    )

    if not require_api_connection("retry_edit"):
        return

    if not features:
        st.info("Upload data before editing.", icon=":material/info:")
        return

    df = flatten_properties(features)

    # Restore last selection (persists across reruns)
    stored = int(st.session_state.get("focus_feature_id", 0) or 0)
    stored = max(0, min(stored, len(features) - 1))

    left, right = st.columns([1.4, 1], gap="large")

    with right:
        # ── TABLE 1: feature list — click row to select, or zoom by ID ───────
        _z_lbl, _z_btn, _z_del = st.columns([3, 0.7, 0.7])
        _z_lbl.markdown("**Feature list**")
        if _z_btn.button(":material/zoom_in:", help="Zoom to selected feature", use_container_width=True, key="zoom_btn"):
            st.session_state["focus_feature_id"] = stored
            st.session_state["zoom_ver"] = st.session_state.get("zoom_ver", 0) + 1
            st.rerun()
        with _z_del:
            st.markdown('<span class="del-feat-mark"></span>', unsafe_allow_html=True)
            if st.button("", icon=":material/delete:", help=f"Delete feature {stored}", use_container_width=True, key="del_feat_btn"):
                try:
                    api_request("DELETE", f"/features/{stored}")
                    st.session_state.pop("focus_feature_id", None)
                    st.session_state.pop("export_bytes", None)
                    st.session_state.pop("zoom_select", None)
                    st.session_state.pop("zoom_ver", None)
                    refresh_features()
                    st.toast(f"Feature {stored} deleted.", icon=":material/check_circle:")
                    st.rerun()
                except APIError as exc:
                    st.error(exc.message, icon=":material/error:")

        sel_event = st.dataframe(
            df,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="feat_list",
            height=220,
        )

        sel_rows = sel_event.selection.rows if sel_event else []
        if sel_rows:
            selected = int(df.iloc[sel_rows[0]]["#"])
            if selected != stored:
                st.session_state["focus_feature_id"] = selected
                st.rerun()
        else:
            selected = stored

        # ── TABLE 2: editable attributes for the selected feature ─────────────
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
                    st.toast(f"Geometry saved for feature {selected}.", icon=":material/check_circle:")
                    st.rerun()
                except json.JSONDecodeError as exc:
                    st.error(f"Invalid JSON: {exc}", icon=":material/error:")
                except APIError as exc:
                    st.error(exc.message, icon=":material/error:")

    with left:
        st.markdown("**Map** — :blue[blue] = selected · :green[green] = others")
        st.caption(
            "Draw a polygon to add it as a new feature automatically. "
            "Enable **Replace mode** to update the selected feature's geometry instead."
        )
        _replace_mode = st.toggle(
            "Replace selected feature geometry",
            value=False,
            key="geom_replace_mode",
            help="When ON, a new drawing replaces the current feature's geometry instead of creating a new feature.",
        )
        map_result = st_folium(
            make_edit_map(features, selected),
            height=MAP_HEIGHT,
            width=None,
            use_container_width=True,
            returned_objects=["last_active_drawing", "all_drawings"],
            key=f"edit_map_{selected}_{len(features)}_{st.session_state.get('zoom_ver', 0)}",
        )

        all_drawings = (map_result or {}).get("all_drawings") or []
        last_active = (map_result or {}).get("last_active_drawing")
        n_drawings = len(all_drawings)

        # Per-map-instance counter so each new map starts clean
        _map_inst = f"_ndraw_{selected}_{len(features)}_{st.session_state.get('zoom_ver', 0)}"
        n_processed = st.session_state.get(_map_inst, 0)

        if not _replace_mode and n_drawings > n_processed:
            # New polygon drawn — auto-create a new feature
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
                    refresh_features()
                    st.toast(
                        f"Feature {new_id} created — enter attributes below.",
                        icon=":material/check_circle:",
                    )
                    st.rerun()
                except APIError as exc:
                    st.error(exc.message, icon=":material/error:")

        # Drawing used by Replace / extent buttons
        drawing = all_drawings[-1] if all_drawings else (last_active or None)

        with st.container(horizontal=True):
            replace_btn = st.button(
                "Replace geometry",
                type="primary",
                icon=":material/save:",
                disabled=not _replace_mode,
                help="Save the drawn polygon as the selected feature's new geometry (Replace mode must be ON).",
            )
            extent_btn = st.button(
                "Full extent",
                icon=":material/fit_screen:",
                help="Zoom out to show all features.",
            )

        if replace_btn:
            geometry = _drawing_to_geometry(drawing)
            if geometry is None:
                st.warning(
                    "Draw a polygon on the map first.",
                    icon=":material/warning:",
                )
            else:
                try:
                    api_request("PUT", f"/features/{selected}/geometry", json={"geometry": geometry})
                    refresh_features()
                    st.session_state[_map_inst] = n_drawings  # mark processed so auto-create skips it
                    st.toast(f"Geometry saved for feature {selected}.", icon=":material/check_circle:")
                    st.rerun()
                except APIError as exc:
                    st.error(exc.message, icon=":material/error:")

        if extent_btn:
            st.session_state.pop("focus_feature_id", None)
            st.rerun()


def render_export_tab(features: list[dict]) -> None:
    st.subheader("Export")
    st.caption("Download the current session as a GeoJSON file after validation, cleanup, or edits.")

    if not require_api_connection("retry_export"):
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
                    st.toast("Ready — click Download GeoJSON to save.", icon=":material/check_circle:")
                    st.rerun()
                except APIError as exc:
                    st.error(exc.message, icon=":material/error:")


# ─── App bootstrap ────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="GeoJSON Tool",
    page_icon=":material/map:",
    layout="wide",
)

st.markdown(
    """
    <style>
    .block-container { padding-top: 1rem; max-width: 1500px; }
    div[data-testid="stMetric"] {
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 0.75rem;
    }
    div[data-testid="stDownloadButton"] > button,
    button[data-testid="stBaseButton-primary"],
    button[kind="primaryFormSubmit"],
    button[kind="primary"] {
        background-color: #16a34a !important;
        border-color: #16a34a !important;
        color: white !important;
    }
    div[data-testid="stDownloadButton"] > button:hover,
    button[data-testid="stBaseButton-primary"]:hover,
    button[kind="primaryFormSubmit"]:hover,
    button[kind="primary"]:hover {
        background-color: #15803d !important;
        border-color: #15803d !important;
    }
    .element-container:has(.del-feat-mark) {
        display: none !important;
    }
    .element-container:has(.del-feat-mark) + .element-container button {
        background-color: #dc2626 !important;
        border-color: #dc2626 !important;
        color: white !important;
    }
    .element-container:has(.del-feat-mark) + .element-container button:hover {
        background-color: #b91c1c !important;
        border-color: #b91c1c !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

init_session()
probe_health()  # sets health_ok in session_state before sidebar reads it

# ─── Sidebar ─────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title(":material/map: GeoJSON Tool")

    with st.container(horizontal=True):
        if st.button("Refresh", icon=":material/refresh:", help="Reload features from the API"):
            refresh_features(show_errors=True)
        if st.button("Clear", icon=":material/delete_sweep:", help="Clear all session data"):
            clear_data()
            st.rerun()

    if st.session_state.get("health_ok", True):
        st.badge("API connected", color="green", icon=":material/check_circle:")
    else:
        st.badge("API offline", color="red", icon=":material/error:")

    _sb_features = st.session_state.get("features", [])
    if _sb_features:
        with st.expander("Symbology", icon=":material/palette:", expanded=False):
            _sym = get_symbology().copy()
            _prop_cols = sorted({k for f in _sb_features for k in (f.get("properties") or {})})
            _col_opts  = [None] + _prop_cols
            _cur_cb    = _sym.get("color_by") if _sym.get("color_by") in _col_opts else None
            _sym["color_by"] = st.selectbox(
                "Color by",
                _col_opts,
                index=_col_opts.index(_cur_cb),
                format_func=lambda v: "Single colour" if v is None else v,
                key="sym_color_by",
            )
            if _sym["color_by"]:
                _uniq = sorted({
                    str((f.get("properties") or {}).get(_sym["color_by"], ""))
                    for f in _sb_features
                })
                _cat_colors = dict(_sym.get("category_colors") or {})
                st.caption("Category colours (auto-assigned, customisable):")
                for _ci, _cv in enumerate(_uniq):
                    _cat_colors[_cv] = st.color_picker(
                        _cv or "(empty)",
                        _cat_colors.get(_cv, _palette_hex(_ci)),
                        key=f"sym_cat_{_cv}",
                    )
                _sym["category_colors"] = _cat_colors
            else:
                _sym["fill_color"] = st.color_picker("Fill colour", _sym["fill_color"], key="sym_fill")
            _sym["stroke_color"] = st.color_picker("Stroke colour", _sym["stroke_color"], key="sym_stroke")
            _sym["fill_opacity"] = st.slider("Opacity", 0.0, 1.0, float(_sym["fill_opacity"]), 0.05, key="sym_opacity")
            _sym["stroke_width"] = st.slider("Stroke width", 1, 6, int(_sym["stroke_width"]), key="sym_sw")
            st.session_state["symbology"] = _sym

    sb_features = _sb_features
    if sb_features:
        st.divider()
        up = st.session_state.get("upload_result") or {}
        loaded = up.get("selected_features", len(sb_features))
        total = up.get("total_features", loaded)
        skipped = max(total - loaded, 0)
        file_name = st.session_state.get("file_name", "Unknown")

        st.caption(f":material/insert_drive_file: **{file_name}**")
        st.caption(f":material/layers: {loaded} feature{'s' if loaded != 1 else ''} loaded"
                   + (f" · {skipped} skipped" if skipped else ""))

# ─── Main ─────────────────────────────────────────────────────────────────────

st.title(":material/map: GeoJSON Tool")
st.caption("Import, validate, inspect, edit, and export farm polygons through the API backend.")

features = st.session_state.get("features")
if features is None:
    features = refresh_features()

tabs = st.tabs([
    ":material/upload_file: Upload",
    ":material/check_circle: Validate",
    ":material/content_copy: Duplicates",
    ":material/edit: Edit",
    ":material/download: Export",
    ":material/smart_toy: Assistant",
])

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

features = st.session_state.get("features", [])

with tabs[5]:
    render_assistant_tab(features, api_request)
