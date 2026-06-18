import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Lets `from assistant import render_assistant_tab` resolve when running
# `streamlit run app.py` directly from ui/ (host dev); in Docker /app already
# contains both ui/'s contents and the copied assistant/ package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistant import render_assistant_tab

from api_client import api_request, clear_data, init_session, probe_health, refresh_features
from map_utils import _palette_hex, get_symbology
from tabs.duplicates import render_duplicate_tab
from tabs.edit import render_edit_tab
from tabs.export import render_export_tab
from tabs.upload import render_upload_tab
from tabs.validate import render_validate_tab

# Console (visible via `docker compose logs ui` / Dozzle) plus a rotating file
# under LOG_DIR, bind-mounted to a host folder in docker-compose.yml so logs
# survive container removal, not just restarts.
LOG_DIR = os.getenv("LOG_DIR", "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(os.path.join(LOG_DIR, "ui.log"), maxBytes=5_000_000, backupCount=3),
    ],
)
logger = logging.getLogger("geojson_dashboard.ui")

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
probe_health()

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
        up_summary = (st.session_state.get("upload_result") or {}).get("summary") or {}
        loaded = up_summary.get("selected_features", len(sb_features))
        total = up_summary.get("total_features", loaded)
        skipped = max(total - loaded, 0)
        file_name = st.session_state.get("file_name", "Unknown")

        st.caption(f":material/insert_drive_file: **{file_name}**")
        st.caption(f":material/layers: {loaded} feature{'s' if loaded != 1 else ''} loaded"
                   + (f" · {skipped} skipped" if skipped else ""))

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
