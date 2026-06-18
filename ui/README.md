# GeoJSON Dashboard UI

A Streamlit dashboard for the API in `../api/`. Upload a GeoJSON file, walk through validation and duplicate detection, inspect the data on maps and tables, edit features, export the cleaned result, and use the Assistant tab to ask grounded questions about the loaded data.

The UI uses a generated `X-Session-ID` so each browser session talks to its own backend dataset.

## How it's built

`app.py` is a bootstrap file and nothing more — it sets the page config, injects a small CSS block (mostly to recolor the primary/download buttons green and the delete button red), wires up logging, sets up the session ID, renders the sidebar, and lays out the six tabs. It has no rendering logic of its own; every tab is one `render_*_tab` function imported from `tabs/`, and `app.py`'s only real job per tab is to re-read `st.session_state["features"]` before handing it to the next one, so a mutation in an earlier tab (say, a delete on the Edit tab... though Edit is actually the fourth tab here) is visible to the ones after it in the same script run.

Everything below `app.py` is split by concern:

- **`api_client.py`** is the one place that talks to the API. `api_request()` is the single HTTP helper every tab goes through — it attaches the session header, raises a uniform `APIError` (with `message`/`errors`/`status_code`) on any failure including a malformed-but-200 response, and logs every call's outcome. Alongside it live the session-ID bootstrap (`init_session`), a 15-second-cached health probe (`probe_health`), the upload helper, `refresh_features()` (which re-pulls `/features` and also updates the cached CRS status), `clear_data()`, and two gate functions — `require_api_connection()` and `require_valid_crs()` — that every tab calls before doing anything else.
- **`map_utils.py`** holds everything map- and table-related: the symbology system (fill/stroke colors, optional categorical coloring by attribute), `flatten_properties()` (turns the feature list into a flat table for `st.dataframe`), the pydeck preview map used on the Upload tab, the Folium edit map with its draw/edit toolbar, and the geometry-diff helper that tells the Edit tab whether a redrawn shape actually changed.
- **`tabs/*.py`** is one `render_*_tab` function per workflow step — `upload.py`, `validate.py`, `duplicates.py`, `edit.py`, `export.py` — each importing only what it needs from the two modules above. The Assistant tab lives outside `ui/` entirely, in the top-level `assistant/` package (see [assistant/README.md](../assistant/README.md)), and is wired in as just another tab from `app.py`.

All tabs share one piece of state, `st.session_state["features"]`, as the locally cached copy of whatever the API currently holds for this session. Nothing renders from a fresher source than that cache — after any backend mutation (upload, edit, delete, fix, duplicate removal), the tab that triggered it calls `refresh_features()` to pull the API's current state back into that cache before the next render.

## The sidebar

The sidebar isn't a tab, but it's worth describing on its own: it shows a live "API connected"/"API offline" badge (backed by the same cached health probe every tab's `require_api_connection()` gate uses), Refresh and Clear buttons that act on the whole session, a Symbology expander (only shown once something is loaded) for picking a single fill color or coloring features by an attribute's value, and — once a file is loaded — the current filename and a loaded/skipped feature count pulled from the last upload's response.

## The tabs

- **Upload.** Drop a `.geojson` file and click Upload. The left column shows what the API actually accepted versus skipped (with a table of why each skipped feature was rejected), and the file's CRS status — accepted, flagged, or simply absent. The right column previews the accepted features on a pydeck map alongside a checkbox-driven attribute table; checking or unchecking a row toggles that feature's visibility on the map above it. If the CRS comes back flagged, the map and table are replaced with an explanation instead of rendering data that would plot in the wrong place.
- **Validate.** Runs the API's geometry checks (ring closure, winding order, holes, self-intersections, empty geometries) and shows a summary plus a row-by-row issue table, each marked with whether it's auto-fixable. "Fix auto-fixable" calls `/fix` and refreshes the feature cache so the rest of the app sees the repaired geometry immediately.
- **Duplicates.** A slider sets the match threshold, then "Scan for duplicates" calls `/duplicates` and shows four summary metrics (duplicate groups, duplicate count, intersect groups, intersect pairs) plus a per-feature table. "Remove duplicates" re-runs the same scan with `remove_duplicates=true`, which deletes the flagged features server-side and refreshes the cache; intersections are shown but never auto-removed, since an overlap between two distinct shapes might be legitimate data rather than a mistake.
- **Edit.** The most interactive tab: a checkbox table on the right controls which features are visible on the Folium map on the left and which one is "active" for the attributes panel below it; the active feature's properties are editable inline, a JSON editor lets you paste a replacement geometry directly, and drawing a new polygon on the map (or dragging the active feature's vertices with the pencil tool) saves automatically — there's no separate "save" step for map edits, the code detects whether a new shape was drawn versus an existing one reshaped and calls the right endpoint either way.
- **Export.** A read-only preview of the current attribute table, plus a download button that asks the API to build the export file the first time it's clicked and then serves it from a cached set of bytes, so re-rendering the page doesn't rebuild the file on every script rerun.
- **Assistant.** A chat interface backed by Gemini, answering questions about whatever's currently loaded through a fixed set of read-only tools. It's implemented in the separate `assistant/` package — see [assistant/README.md](../assistant/README.md) for how it's grounded and kept from making things up.

Validate, Duplicates, Edit, Export, and Assistant all start with the same two checks — is the API reachable, and is the loaded file's CRS one this app trusts — before rendering anything else. Upload is the one exception: it always renders the upload form itself, but hides its own map/table preview under the same CRS gate once a flagged file has been loaded.

## Non-obvious Streamlit patterns used here

A few things in this codebase look like workarounds because they are — Streamlit's rerun-the-whole-script model has some sharp edges, and these are the patterns used to work around them:

- **Widget state can't be written after the widget has already rendered in the same script run.** Doing `st.session_state[key] = ...` for a widget's own `key` after that widget has rendered raises `StreamlitAPIException`. The fix used throughout (see the feature-list checkbox tables in `tabs/edit.py` and `tabs/upload.py`) is a "pending state" key — e.g. `_pending_feat_rows` — that gets applied to the real widget key *before* that widget is instantiated on the *next* run, never the current one.
- **`st.dataframe(..., selection_mode="multi-row", selection_default=...)`** is how the "checkbox per row, all checked by default" feature-visibility tables work. `selection_default` only takes effect on the very first render when no prior selection is stored — making a newly-created row show up pre-checked later means mutating the pending-state key above, not relying on `selection_default` again.
- **The Edit tab's map pan/zoom is deliberately decoupled from feature selection.** `streamlit_folium` identifies a map by hashing its rendered Leaflet HTML, so any visual change — selecting a different feature, toggling visibility — forces a full component remount, which would otherwise re-center the map on every click. Pan/zoom state lives separately in `st.session_state["edit_map_view"]` and only changes when the zoom or full-extent buttons are pressed, but is still passed via `st_folium`'s `zoom=`/`center=` kwargs on every render so it survives the remount.
- **Editing an existing geometry's vertices auto-saves.** The Draw plugin reports both newly-drawn shapes and in-place edits through the same `all_drawings` array; `render_edit_tab` tells them apart by whether the feature count grew (a new shape) or stayed the same with different coordinates than the preloaded baseline (an edit), and calls `POST /features` or `PUT /features/{id}/geometry` accordingly. There's no manual "replace mode" toggle — an earlier version had one, and it turned out to be the actual cause of a "can't edit vertices" bug, since the edit was captured by the map widget but never reached the API without it.
- **`GeoJsonTooltip`/`GeoJson` layers must be skipped entirely when the feature collection passed to them is empty** (e.g. every checkbox unchecked) — Folium raises `AssertionError` otherwise.
- **Logging mirrors the API's pattern.** `app.py` calls `logging.basicConfig()` once at startup; `api_client.py`, each `tabs/*.py` module, and `assistant/assistant.py` each get their own child logger (`geojson_dashboard.ui.*`, `geojson_dashboard.assistant`) so every API call's outcome, every upload/edit/delete/export, and every assistant tool call is visible in the console or via `docker compose logs ui`.

## Running Locally

```bash
cd ui
pip install -r requirements.txt
streamlit run app.py
```

The API must be reachable. For local non-Docker use, `API_BASE_URL` should normally be:

```text
API_BASE_URL=http://localhost:8000
```

The dashboard opens at http://localhost:8501.

## Running With Docker

From the repo root:

```bash
docker compose up --build -d ui
docker compose logs ui --tail 50
```

The split UI image copies both `ui/` and `../assistant/` because the Assistant tab imports the assistant package as a sibling module. The single-container app in the root `Dockerfile` also includes the UI and assistant together.

## Configuration

Copy `.env.example` to `.env` and fill in what you need:

| Variable | Purpose |
| --- | --- |
| `GEMINI_API_KEY` | Required only for the Assistant tab. The rest of the dashboard works without it. |
| `GEMINI_MODEL` | Optional Gemini model override. Defaults to `gemini-2.5-flash` in the assistant code. |
| `LIMIT` | Per-session message cap for the assistant. Defaults to `100`. |
| `API_BASE_URL` | Where the UI calls the API. Use `http://api:8000` in split Docker Compose, `http://127.0.0.1:8000` in the single-container app, and `http://localhost:8000` when running directly on the host. |

`.env` is loaded with `python-dotenv` and is git-ignored. Do not commit real API keys.

## Code Layout

- `app.py`: page setup, CSS, logging, session init, sidebar, and tab wiring.
- `api_client.py`: shared HTTP helper, session helpers, health checks, upload, refresh, clear, and the API-connection/CRS gating used by every tab.
- `map_utils.py`: pydeck preview maps, Folium edit map, symbology helpers, geometry conversion helpers, and attribute flattening.
- `tabs/upload.py`: upload workflow and initial map/table preview.
- `tabs/validate.py`: geometry validation and auto-fix UI.
- `tabs/duplicates.py`: duplicate and intersection scan UI.
- `tabs/edit.py`: feature visibility, attribute editing, delete, draw, reshape, and geometry JSON editing.
- `tabs/export.py`: final preview and download.

## Logging

Each UI module uses a child logger such as `geojson_dashboard.ui.upload`. The logs include uploads, validation runs, duplicate scans, edits, deletes, exports, and API request outcomes. In Docker, view them with:

```bash
docker compose logs ui --tail 50
```

## Limitations

- **The UI isn't responsive.** It's laid out and tested for a normal desktop browser window — multi-column layouts, the side-by-side map/table panes on Upload and Edit, and the sidebar are not adapted for small screens or mobile widths, and will likely look cramped or overlap on one.
- **Streamlit reruns the script after interactions.** This keeps the code simple but can feel slow on larger datasets because maps and tables redraw often.
- **Editing a geometry on the map can feel slow.** Every drawn shape or dragged vertex round-trips to the API, reruns the whole Streamlit script, and re-renders the Folium map from scratch — there's no incremental update. On a normal-sized feature this is a brief pause; the bigger or more complex the geometry, the more noticeable it gets. This is a property of the current Python/Streamlit interface, not of the geometry itself.
- **The app doesn't handle complex geometries well, and can't reliably modify them on the map.** The Edit tab's auto-save logic (`ui/tabs/edit.py`) assumes one feature maps to exactly one drawn shape; a `Polygon` with holes fits that assumption fine, but a `MultiPolygon` with more than one part does not — the preload macro (`map_utils.py`'s `_PreloadGeometry`) puts each part on the map as its own separate shape, so reshaping a multi-part feature by dragging its vertices can be misread as drawing a brand-new feature instead of editing the existing one. Use the "Edit geometry as JSON" editor for multi-part `MultiPolygon` features instead of the map.
- **Only the selected feature is directly reshapeable on the edit map.** Other visible features are shown for context, but to drag vertices you must select the feature first.
- **No undo button.** Deletes, duplicate removals, saved attributes, and saved geometry edits update the active API session immediately. Re-uploading the original file is the current recovery path.
- **Single active dataset.** The UI does not compare two files side by side, merge multiple uploads, or preserve per-file provenance after upload.
- **Tables are for inspection and light editing.** They are not full spreadsheets. There is no bulk find/replace, formula support, controlled vocabulary editor, or schema validation.
- **Manual geometry JSON editing needs care.** The JSON editor saves a geometry object if the API accepts its basic type and coordinate structure. Users should run Validate after manual geometry edits.
- **Symbology is not exported.** Map colors help inspect the current session but are not written into the exported GeoJSON.
- **Assistant availability depends on Gemini.** If `GEMINI_API_KEY` is missing, invalid, rate-limited, or the Gemini API is unreachable, the Assistant tab cannot answer. The rest of the app still works.
- **CRS is flagged, not reprojected.** The app detects when an uploaded file's CRS isn't WGS84/CRS84 (or its `EPSG:4326` alias) and blocks the tabs that would otherwise compute wrong areas or positions from it, but it cannot transform the coordinates itself — the only fix is re-exporting the source file in WGS84/CRS84 before re-uploading.

## Useful Improvements To Add Next

- Make the layout responsive, or at minimum usable, on narrower/mobile screens.
- Add multi-file upload with merge rules and source-file tracking.
- Add undo/version history for edits, auto-fixes, and duplicate removals.
- Add stable feature IDs so deleting one feature does not shift later IDs.
- Add table-level bulk editing for common attribute cleanup tasks.
- Add CRS reprojection (e.g. via `pyproj`) instead of only flagging non-WGS84 files.
- Add background jobs, progress indicators, pagination, and spatial indexes for larger datasets.
