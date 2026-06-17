import json
from typing import Any

import pandas as pd
import pydeck as pdk
import streamlit as st
from folium import GeoJson, GeoJsonTooltip, MacroElement, Map
from folium.plugins import Draw
from jinja2 import Template

MAP_HEIGHT = 520

_DEFAULT_SYMBOLOGY: dict = {
    "fill_color":      "#3b82f6",
    "stroke_color":    "#1e3a5f",
    "fill_opacity":    0.35,
    "stroke_width":    2,
    "color_by":        None,
    "category_colors": {},
}

_PALETTE = [
    [30, 104, 175],
    [232, 120, 73],
    [65, 148, 108],
    [164, 93, 176],
    [210, 151, 55],
    [77, 152, 163],
]


class _PreloadGeometry(MacroElement):
    """Injects a feature into the Leaflet Draw layer so it's immediately
    editable (vertex dragging) without the user having to redraw it."""

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


def get_symbology() -> dict:
    return {**_DEFAULT_SYMBOLOGY, **st.session_state.get("symbology", {})}


def hex_to_rgba(hex_color: str, opacity: float = 1.0) -> list[int]:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return [r, g, b, int(opacity * 255)]


def _palette_hex(idx: int) -> str:
    r, g, b = _PALETTE[idx % len(_PALETTE)]
    return f"#{r:02x}{g:02x}{b:02x}"


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


def update_map_bounds(features: list[dict], focus_id: int | set[int] | list[int] | None = None) -> dict:
    points = []
    if focus_id is not None:
        ids = [focus_id] if isinstance(focus_id, int) else list(focus_id)
        for fid in ids:
            if 0 <= fid < len(features):
                points.extend(collect_geometry_points(features[fid].get("geometry") or {}))
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


def make_preview_map(
    features: list[dict],
    focus_id: int | set[int] | list[int] | None = None,
    visible_ids: set[int] | None = None,
) -> pdk.Deck:
    sym = get_symbology()
    color_by = sym.get("color_by")
    cat_colors = sym.get("category_colors") or {}
    opacity = sym["fill_opacity"]
    base_fill = hex_to_rgba(sym["fill_color"], opacity)
    view = pdk.ViewState(**update_map_bounds(features, focus_id), pitch=0)
    seen_cats: list[str] = []
    rendered = []

    for i, feature in enumerate(features):
        if visible_ids is not None and i not in visible_ids:
            continue
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


def _round_coords(value: Any, ndigits: int = 9) -> Any:
    if isinstance(value, list):
        return [_round_coords(v, ndigits) for v in value]
    if isinstance(value, (int, float)):
        return round(value, ndigits)
    return value


def _geometries_equal(a: dict | None, b: dict | None) -> bool:
    """Compare geometries ignoring float round-trip noise from the map widget."""
    if not a or not b:
        return a == b
    return (
        a.get("type") == b.get("type")
        and _round_coords(a.get("coordinates")) == _round_coords(b.get("coordinates"))
    )


def make_edit_map(features: list[dict], selected_id: int, view: dict, visible_ids: set[int] | None = None) -> Map:
    sym = get_symbology()
    fmap = Map(
        location=[view["latitude"], view["longitude"]],
        zoom_start=view["zoom"],
        control_scale=True,
        tiles="OpenStreetMap",
    )

    # Selected feature is always blue; others use the user's symbology.
    # Unchecked (hidden) features are skipped entirely.
    collection = {"type": "FeatureCollection", "features": []}
    for i, f in enumerate(features):
        if visible_ids is not None and i not in visible_ids:
            continue
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

    if collection["features"]:
        GeoJson(
            collection,
            name="Features",
            tooltip=GeoJsonTooltip(fields=["feature_id"], aliases=["Feature"]),
            style_function=_edit_style,
            highlight_function=lambda _: {"weight": 4, "fillOpacity": 0.50},
        ).add_to(fmap)

    # edit_options makes the Draw toolbar show an edit (pencil) button
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

    # Pre-load the selected feature into the Draw layer so its vertices can
    # be edited immediately without redrawing it.
    selected_geom = features[selected_id].get("geometry") or {}
    if selected_geom.get("coordinates"):
        drawn_items_var = f"drawnItems_{draw.get_name()}"
        _PreloadGeometry(drawn_items_var, selected_geom).add_to(fmap)

    return fmap
