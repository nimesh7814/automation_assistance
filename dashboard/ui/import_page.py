import json

import geopandas as gpd
import pydeck as pdk
import streamlit as st
from shapely.validation import explain_validity

try:
    from shapely import make_valid
except ImportError:
    make_valid = None

MAP_HEIGHT = 650

st.set_page_config(page_title="GeoJSON Viewer", layout="wide")

st.markdown(
    """
    <style>
    section[data-testid="stSidebar"] { display: none; }
    [data-testid="collapsedControl"] { display: none; }
    [data-testid="stAppViewContainer"] > .main { margin-left: 0; }

    .block-container,
    [data-testid="stMainBlockContainer"] {
        max-width: none !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
        padding-top: 1rem !important;
        padding-bottom: 0 !important;
        width: 100% !important;
    }

    div[data-testid="stHorizontalBlock"]:has(.st-key-map_tile):has(.st-key-import_options_tile) {
        align-items: stretch !important;
        display: flex !important;
        width: 100% !important;
    }

    div[data-testid="stHorizontalBlock"]:has(.st-key-map_tile):has(.st-key-import_options_tile) > div {
        display: flex !important;
        flex-direction: column !important;
    }

    .st-key-map_tile,
    .st-key-import_options_tile {
        min-height: calc(100vh - 110px) !important;
    }

    .st-key-map_tile [data-testid="stDeckGlJsonChart"],
    .st-key-map_tile iframe {
        height: calc(100vh - 210px) !important;
        min-height: 420px !important;
    }

    .st-key-import_options_tile [data-testid="stVerticalBlockBorderWrapper"] {
        min-height: calc(100vh - 110px) !important;
    }

    /* GitHub link */
    .github-link-container {
        position: fixed;
        top: 14px;
        right: 120px;
        z-index: 999999;
    }

    .github-link-container a {
        display: flex;
        align-items: center;
        gap: 6px;
        text-decoration: none;
        color: #31333f;
        font-size: 14px;
        font-weight: 500;
        padding: 4px 10px;
        border-radius: 6px;
        transition: background-color 0.15s ease;
    }

    .github-link-container a:hover {
        background-color: rgba(49, 51, 63, 0.08);
        color: #31333f;
    }

    .github-link-container svg { flex-shrink: 0; }
    </style>

    <div class="github-link-container">
        <a href="https://github.com/nimesh7814/automation_assistance" target="_blank" rel="noopener noreferrer">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0 1 12 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z"/>
            </svg>
            GitHub
        </a>
    </div>
    """,
    unsafe_allow_html=True,
)


def save_uploaded_file(file_content, file_name):
    import tempfile
    import os
    import uuid

    _, file_extension = os.path.splitext(file_name)
    file_id = str(uuid.uuid4())
    file_path = os.path.join(tempfile.gettempdir(), f"{file_id}{file_extension}")

    with open(file_path, "wb") as file:
        file.write(file_content.getbuffer())

    return file_path


def gdf_centroid(gdf):
    projected = gdf.to_crs(4326) if gdf.crs is not None else gdf.set_crs(4326)
    bounds = projected.total_bounds
    lon = (bounds[0] + bounds[2]) / 2
    lat = (bounds[1] + bounds[3]) / 2
    return lon, lat


def gdf_zoom(gdf):
    projected = gdf.to_crs(4326) if gdf.crs is not None else gdf.set_crs(4326)
    min_lon, min_lat, max_lon, max_lat = projected.total_bounds
    span = max(max_lon - min_lon, max_lat - min_lat)

    if span <= 0:
        return 14
    if span > 120:
        return 1
    if span > 60:
        return 2
    if span > 30:
        return 3
    if span > 15:
        return 4
    if span > 8:
        return 5
    if span > 4:
        return 6
    if span > 2:
        return 7
    if span > 1:
        return 8
    if span > 0.5:
        return 9
    if span > 0.25:
        return 10
    if span > 0.1:
        return 11
    if span > 0.05:
        return 12
    return 13


def gdf_view_state(gdf):
    lon, lat = gdf_centroid(gdf)
    return {"latitude": lat, "longitude": lon, "zoom": gdf_zoom(gdf)}


def attribute_table(gdf):
    if gdf.geometry.name in gdf.columns:
        return gdf.drop(columns=[gdf.geometry.name])
    return gdf.copy()


def hex_to_rgba(hex_color, opacity):
    hex_color = hex_color.lstrip("#")
    return [
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
        int(opacity * 255),
    ]


def default_category_color(index):
    palette = [
        "#ef4444",
        "#3b82f6",
        "#22c55e",
        "#f59e0b",
        "#8b5cf6",
        "#06b6d4",
        "#ec4899",
        "#84cc16",
        "#f97316",
        "#64748b",
    ]
    return palette[index % len(palette)]


def feature_style_gdf(gdf, color_column, category_colors, opacity):
    styled_gdf = gdf.to_crs(4326) if gdf.crs is not None else gdf.set_crs(4326)
    styled_gdf = styled_gdf.copy()

    if color_column and color_column in styled_gdf.columns:
        colors = styled_gdf[color_column].astype("string").fillna("None").map(
            lambda value: hex_to_rgba(category_colors.get(value, "#3b82f6"), opacity)
        )
    else:
        colors = [[59, 130, 246, int(opacity * 255)]] * len(styled_gdf)

    styled_gdf["__fill_r"] = [color[0] for color in colors]
    styled_gdf["__fill_g"] = [color[1] for color in colors]
    styled_gdf["__fill_b"] = [color[2] for color in colors]
    styled_gdf["__fill_a"] = [color[3] for color in colors]
    return styled_gdf


def make_deck(
    gdf=None,
    color_column=None,
    category_colors=None,
    opacity=0.7,
    visible_rows=None,
    view_state=None,
):
    if gdf is None:
        return pdk.Deck(
            map_style="light",
            initial_view_state=pdk.ViewState(latitude=20, longitude=0, zoom=1.2),
        )

    if visible_rows is None:
        valid_visible_rows = list(range(len(gdf)))
    else:
        valid_visible_rows = [row for row in visible_rows if 0 <= row < len(gdf)]

    if view_state is None:
        view_state = gdf_view_state(gdf)

    visible_gdf = gdf.iloc[valid_visible_rows]
    styled_gdf = feature_style_gdf(
        visible_gdf, color_column, category_colors or {}, opacity
    )
    geojson = json.loads(styled_gdf.to_json())

    layers = [
        pdk.Layer(
            "GeoJsonLayer",
            data=geojson,
            pickable=True,
            stroked=True,
            filled=True,
            get_fill_color="[properties.__fill_r, properties.__fill_g, properties.__fill_b, properties.__fill_a]",
            get_line_color=[30, 41, 59, 220],
            line_width_min_pixels=1,
        )
    ]

    return pdk.Deck(
        layers=layers,
        map_style="light",
        initial_view_state=pdk.ViewState(**view_state),
        tooltip={"text": "{fid}"},
    )


def validate_gdf(gdf):
    invalid_rows = []
    for index, geometry in gdf.geometry.items():
        if geometry is None or geometry.is_empty:
            invalid_rows.append(
                {"row": index, "status": "empty", "reason": "Missing or empty geometry"}
            )
        elif not geometry.is_valid:
            invalid_rows.append(
                {"row": index, "status": "invalid", "reason": explain_validity(geometry)}
            )

    return {
        "total_features": len(gdf),
        "valid_features": len(gdf) - len(invalid_rows),
        "invalid_features": len(invalid_rows),
        "issues": invalid_rows,
    }


def fix_gdf(gdf):
    fixed_gdf = gdf.copy()
    fixed_rows = []

    for index, geometry in fixed_gdf.geometry.items():
        if geometry is None or geometry.is_empty or geometry.is_valid:
            continue

        fixed_geometry = make_valid(geometry) if make_valid else geometry.buffer(0)
        fixed_gdf.at[index, fixed_gdf.geometry.name] = fixed_geometry

        fixed_rows.append(
            {
                "row": index,
                "before": explain_validity(geometry),
                "after": "valid" if fixed_geometry.is_valid else explain_validity(fixed_geometry),
            }
        )

    return fixed_gdf, {
        "fixed_features": sum(1 for row in fixed_rows if row["after"] == "valid"),
        "remaining_invalid": sum(1 for row in fixed_rows if row["after"] != "valid"),
        "details": fixed_rows,
    }


def render_validate_result(result):
    st.markdown("#### Validate Result")
    st.dataframe(
        [
            {"Metric": "Total features", "Value": result["total_features"]},
            {"Metric": "Valid features", "Value": result["valid_features"]},
            {"Metric": "Invalid features", "Value": result["invalid_features"]},
        ],
        width="stretch",
        hide_index=True,
    )
    if result["issues"]:
        st.markdown("Invalid Rows")
        st.dataframe(result["issues"], width="stretch", hide_index=True)
    else:
        st.success("No invalid geometries found.")


def render_fix_result(result):
    st.markdown("#### Fix Result")
    st.dataframe(
        [
            {"Metric": "Fixed features", "Value": result["fixed_features"]},
            {"Metric": "Remaining invalid", "Value": result["remaining_invalid"]},
        ],
        width="stretch",
        hide_index=True,
    )
    if result["details"]:
        st.markdown("Fixed Rows")
        st.dataframe(result["details"], width="stretch", hide_index=True)
    else:
        st.info("No invalid geometries needed fixing.")


def app():

    left_col, right_col = st.columns([2, 1])
    data = None

    gdf = st.session_state.get("import_gdf")
    attributes = attribute_table(gdf) if gdf is not None else None

    with right_col:
        with st.container(border=True, key="import_options_tile"):
            st.subheader("Import Options")

            data = st.file_uploader(
                "Upload a GeoJSON file",
                type=["geojson"],
            )

            if data is None:
                st.session_state.pop("import_file_name", None)
                st.session_state.pop("import_gdf", None)
                st.session_state.pop("import_map_view_state", None)
                st.session_state.pop("import_file_token", None)
                st.session_state["import_options_locked"] = False
                gdf = None
                attributes = None
            elif st.session_state.get("import_file_name") != data.name:
                file_path = save_uploaded_file(data, data.name)
                st.session_state["import_gdf"] = gpd.read_file(file_path)
                st.session_state["import_file_name"] = data.name
                st.session_state["import_file_token"] = file_path
                st.session_state.pop("import_map_view_state", None)
                st.session_state["import_options_locked"] = True
                gdf = st.session_state["import_gdf"]
                attributes = attribute_table(gdf)

            validate = st.session_state.get("validate_option", False)
            fix = st.session_state.get("fix_option", False)
            color_column = None
            category_colors = {}
            opacity = 0.7
            visible_rows = list(range(len(gdf))) if gdf is not None else []

            with st.expander("Validation & Fix Geometry", expanded=False):
                validate_col, fix_col = st.columns(2)
                with validate_col:
                    validate = st.checkbox(
                        "Validate",
                        key="validate_option",
                        disabled=st.session_state.get("import_options_locked", False),
                    )
                with fix_col:
                    fix = st.checkbox(
                        "Fix",
                        key="fix_option",
                        disabled=st.session_state.get("import_options_locked", False),
                    )

                if st.session_state.get("import_options_locked", False):
                    st.caption("Selection is locked for the uploaded file.")

            if attributes is not None:
                column_names = attributes.columns.values.tolist()
                with st.expander("Symbology", expanded=False):
                    color_by_category = st.checkbox("Color by category", True)
                    opacity = st.slider("Opacity", 0.05, 1.0, 0.7, 0.05)

                    if color_by_category and column_names:
                        color_column = st.selectbox(
                            "Category column",
                            column_names,
                        )
                        categories = (
                            attributes[color_column]
                            .astype("string")
                            .fillna("None")
                            .drop_duplicates()
                            .sort_values()
                            .tolist()
                        )

                        if len(categories) > 25:
                            st.warning("Showing color controls for the first 25 categories.")
                            categories = categories[:25]

                        for index, category in enumerate(categories):
                            color_key = f"color_{color_column}_{category}"
                            color_col, label_col = st.columns([1, 4])
                            with color_col:
                                category_colors[category] = st.color_picker(
                                    str(category),
                                    st.session_state.get(
                                        color_key, default_category_color(index)
                                    ),
                                    key=color_key,
                                    label_visibility="collapsed",
                                )
                            with label_col:
                                st.write(str(category))

                st.subheader("Attribute Table")
                if attributes.empty:
                    st.info("This GeoJSON has no attribute columns.")
                else:
                    visible_rows = []
                    file_token = st.session_state.get("import_file_token", data.name)
                    table_columns = attributes.columns.tolist()
                    header_columns = st.columns([0.6, 0.6] + [2] * len(table_columns))

                    header_columns[0].markdown("Show")
                    header_columns[1].markdown("Zoom")
                    for header_column, column_name in zip(
                        header_columns[2:], table_columns
                    ):
                        header_column.markdown(str(column_name))

                    for row_position, (row_index, row) in enumerate(
                        attributes.iterrows()
                    ):
                        row_columns = st.columns(
                            [0.6, 0.6] + [2] * len(table_columns)
                        )
                        visible_key = f"attribute_visible_{file_token}_{row_position}"
                        if visible_key not in st.session_state:
                            st.session_state[visible_key] = True

                        with row_columns[0]:
                            is_visible = st.checkbox(
                                f"Show row {row_position + 1}",
                                key=visible_key,
                                label_visibility="collapsed",
                            )
                        if is_visible:
                            visible_rows.append(row_position)

                        with row_columns[1]:
                            if st.button(
                                "⌖",
                                key=f"zoom_attribute_{file_token}_{row_position}",
                                help=f"Zoom to row {row_position + 1}",
                            ):
                                st.session_state["import_map_view_state"] = (
                                    gdf_view_state(gdf.iloc[[row_position]])
                                )

                        for value_column, column_name in zip(
                            row_columns[2:], table_columns
                        ):
                            value_column.write(row[column_name])

                    st.caption(
                        f"{len(visible_rows)} of {len(attributes)} rows are shown on the map."
                    )

    with left_col:
        with st.container(border=True, key="map_tile"):
            st.subheader("Map")
            if gdf is not None:
                deck = make_deck(
                    gdf,
                    color_column=color_column,
                    category_colors=category_colors,
                    opacity=opacity,
                    visible_rows=visible_rows,
                    view_state=st.session_state.get("import_map_view_state"),
                )
                st.pydeck_chart(deck, height=MAP_HEIGHT)
            else:
                st.pydeck_chart(make_deck(), height=MAP_HEIGHT)

    if gdf is not None:
        selected_results = []
        if validate:
            selected_results.append(("validate", validate_gdf(gdf)))
        if fix:
            _fixed_gdf, fix_result = fix_gdf(gdf)
            selected_results.append(("fix", fix_result))

        if selected_results:
            st.subheader("Results")
            result_columns = st.columns(len(selected_results))
            for result_column, (result_type, result) in zip(
                result_columns, selected_results
            ):
                with result_column:
                    with st.container(border=True):
                        if result_type == "validate":
                            render_validate_result(result)
                        else:
                            render_fix_result(result)

    return

    # JS: enforces tile heights through Streamlit's inner wrapper chain on every
    # rerender. CSS cannot pierce dynamically-assigned inline heights in nested
    # Streamlit elements, so we use window.parent DOM access directly.
    components.html(
        """
        <script>
        (function () {
            var rafId, timer;

            function px(n) { return n + 'px'; }

            function apply() {
                var doc = window.parent.document;
                var vh  = window.parent.innerHeight;
                var tileH = px(vh - 90);

                // ── MAP TILE ─────────────────────────────────────────────────
                var map = doc.querySelector('.st-key-map_tile');
                if (map) {
                    // Outer tile: fixed height
                    map.style.setProperty('height',     tileH,    'important');
                    map.style.setProperty('min-height', tileH,    'important');
                    map.style.setProperty('overflow',   'hidden',  'important');

                    // Emotion-cache wrapper (direct child) fills tile
                    var ec = map.firstElementChild;
                    if (ec) {
                        ec.style.setProperty('height',   '100%',   'important');
                        ec.style.setProperty('overflow', 'hidden',  'important');
                    }

                    // Border wrapper: turn into flex column so inner block can grow
                    var bw = map.querySelector('[data-testid="stVerticalBlockBorderWrapper"]');
                    if (bw) {
                        bw.style.setProperty('height',          '100%',   'important');
                        bw.style.setProperty('display',         'flex',   'important');
                        bw.style.setProperty('flex-direction',  'column', 'important');
                        bw.style.setProperty('overflow',        'hidden', 'important');

                        // Inner content block (stVerticalBlock) grows to fill border wrapper
                        var ivb = bw.querySelector('[data-testid="stVerticalBlock"]');
                        if (ivb) {
                            ivb.style.setProperty('flex',           '1 1 0',  'important');
                            ivb.style.setProperty('min-height',     '0',      'important');
                            ivb.style.setProperty('display',        'flex',   'important');
                            ivb.style.setProperty('flex-direction', 'column', 'important');

                            // Last child of inner block = pydeck element container.
                            // Make it fill remaining space after the heading.
                            var kids = ivb.children;
                            if (kids.length > 0) {
                                var last = kids[kids.length - 1];
                                last.style.setProperty('flex',       '1 1 0', 'important');
                                last.style.setProperty('min-height', '0',     'important');

                                // Every descendant inside the chart container fills height,
                                // except <canvas> / <svg> (WebGL manages its own size).
                                var desc = last.querySelectorAll('*');
                                for (var i = 0; i < desc.length; i++) {
                                    var tag = desc[i].tagName.toLowerCase();
                                    if (tag !== 'canvas' && tag !== 'svg' && tag !== 'path') {
                                        desc[i].style.setProperty('height',     '100%', 'important');
                                        desc[i].style.setProperty('min-height', '0',    'important');
                                    }
                                }
                            }
                        }
                    }
                }

                // ── IMPORT OPTIONS TILE ───────────────────────────────────────
                var imp = doc.querySelector('.st-key-import_options_tile');
                if (imp) {
                    // Outer tile: fixed height, clip
                    imp.style.setProperty('height',     tileH,   'important');
                    imp.style.setProperty('min-height', tileH,   'important');
                    imp.style.setProperty('overflow',   'hidden', 'important');

                    // Emotion-cache wrapper fills tile
                    var ec2 = imp.firstElementChild;
                    if (ec2) {
                        ec2.style.setProperty('height',   '100%',   'important');
                        ec2.style.setProperty('overflow', 'hidden',  'important');
                    }

                    // Border wrapper fills tile height and scrolls its content.
                    // Do NOT set height on the inner stVerticalBlock — content must
                    // flow naturally from the top downward.
                    var bw2 = imp.querySelector('[data-testid="stVerticalBlockBorderWrapper"]');
                    if (bw2) {
                        bw2.style.setProperty('height',     '100%',  'important');
                        bw2.style.setProperty('overflow-y', 'auto',  'important');
                        bw2.style.setProperty('overflow-x', 'hidden','important');
                    }
                }
            }

            function schedule() {
                cancelAnimationFrame(rafId);
                clearTimeout(timer);
                // Wait one frame after the 60 ms quiet period so Streamlit has
                // finished its own style mutations before we apply ours.
                timer = setTimeout(function () {
                    rafId = requestAnimationFrame(apply);
                }, 60);
            }

            schedule();
            window.parent.addEventListener('resize', schedule);
            new MutationObserver(schedule).observe(
                window.parent.document.body,
                { childList: true, subtree: true }
            );
        })();
        </script>
        """,
        height=0,
    )
