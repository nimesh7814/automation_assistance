# GeoJSON Dashboard UI

A Streamlit dashboard for the API in `../api/`. Upload a GeoJSON file, walk through validation and duplicate detection, inspect the data on maps and tables, edit features, export the cleaned result, and use the Assistant tab to ask grounded questions about the loaded data.

The UI uses a generated `X-Session-ID` so each browser session talks to its own backend dataset.

## Tabs

- **Upload**: drop a `.geojson` file, see accepted and skipped features, preview the geometries on a map, inspect attributes in a selectable table, and see whether the file's coordinate reference system (CRS) was accepted.
- **Validate**: run geometry validation for invalid rings, winding problems, self-intersections, empty geometry, and hole placement issues. Auto-fix the subset that is safe to repair mechanically.
- **Duplicates**: scan for duplicate geometries and intersecting geometry groups with an adjustable threshold. Duplicate features can be removed from the session.
- **Edit**: show or hide features, select a feature, edit its attributes, draw new polygons, delete features, reshape the selected geometry, or paste a GeoJSON geometry object.
- **Export**: preview the current table and download the session's current GeoJSON.
- **Assistant**: ask Gemini-powered natural-language questions about the loaded data through fixed read-only tools. The assistant is disabled unless `GEMINI_API_KEY` is configured.

Validate, Duplicates, Edit, Export, and Assistant all check the uploaded file's CRS first: if the API flagged it as not WGS84/CRS84 (see the root and `api/` READMEs), each of those tabs shows a blocking error instead of its normal content, since any area, position, or edit computed from non-WGS84 coordinates would be wrong. Re-upload the file in WGS84/CRS84 to clear it.

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

| Variable         | Purpose                                                                                                                                                                                        |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GEMINI_API_KEY` | Required only for the Assistant tab. The rest of the dashboard works without it.                                                                                                               |
| `GEMINI_MODEL`   | Optional Gemini model override. Defaults to `gemini-2.5-flash` in the assistant code.                                                                                                          |
| `LIMIT`          | Per-session message cap for the assistant. Defaults to `100`.                                                                                                                                  |
| `API_BASE_URL`   | Where the UI calls the API. Use `http://api:8000` in split Docker Compose, `http://127.0.0.1:8000` in the single-container app, and `http://localhost:8000` when running directly on the host. |

`.env` is loaded with `python-dotenv` and is git-ignored. Do not commit real API keys.

## Code Layout

- `app.py`: page setup, CSS, logging, session init, sidebar, and tab wiring.
- `api_client.py`: shared HTTP helper, session helpers, health checks, upload, refresh, clear, and API connection gating.
- `map_utils.py`: pydeck preview maps, Folium edit map, symbology helpers, geometry conversion helpers, and attribute flattening.
- `tabs/upload.py`: upload workflow and initial map/table preview.
- `tabs/validate.py`: geometry validation and auto-fix UI.
- `tabs/duplicates.py`: duplicate and intersection scan UI.
- `tabs/edit.py`: feature visibility, attribute editing, delete, draw, reshape, and geometry JSON editing.
- `tabs/export.py`: final preview and download.

All tabs share `st.session_state["features"]` as the local cache of the current backend session. After a backend mutation, the tab should call `refresh_features()`.

## Logging

Each UI module uses a child logger such as `geojson_dashboard.ui.upload`. The logs include uploads, validation runs, duplicate scans, edits, deletes, exports, and API request outcomes. In Docker, view them with:

```bash
docker compose logs ui --tail 50
```

## Limitations

- **Streamlit reruns the script after interactions.** This keeps the code simple but can feel slow on larger datasets because maps and tables redraw often.
- **Only the selected feature is directly reshapeable on the edit map.** Other visible features are shown for context, but to drag vertices you must select the feature first.
- **No undo button.** Deletes, duplicate removals, saved attributes, and saved geometry edits update the active API session immediately. Re-uploading the original file is the current recovery path.
- **Single active dataset.** The UI does not compare two files side by side, merge multiple uploads, or preserve per-file provenance after upload.
- **Tables are for inspection and light editing.** They are not full spreadsheets. There is no bulk find/replace, formula support, controlled vocabulary editor, or schema validation.
- **Manual geometry JSON editing needs care.** The JSON editor saves a geometry object if the API accepts its basic type and coordinate structure. Users should run Validate after manual geometry edits.
- **Symbology is not exported.** Map colors help inspect the current session but are not written into the exported GeoJSON.
- **Assistant availability depends on Gemini.** If `GEMINI_API_KEY` is missing, invalid, rate-limited, or the Gemini API is unreachable, the Assistant tab cannot answer. The rest of the app still works.
- **CRS is flagged, not reprojected.** The app detects when an uploaded file's CRS isn't WGS84/CRS84 and blocks the tabs that would otherwise compute wrong areas or positions from it, but it cannot transform the coordinates itself — the only fix is re-exporting the source file in WGS84/CRS84 before re-uploading.

## Useful Improvements To Add Next

- Add multi-file upload with merge rules and source-file tracking.
- Add undo/version history for edits, auto-fixes, and duplicate removals.
- Add stable feature IDs so deleting one feature does not shift later IDs.
- Add table-level bulk editing for common attribute cleanup tasks.
- Add CRS reprojection (e.g. via `pyproj`) instead of only flagging non-WGS84 files.
- Add background jobs, progress indicators, pagination, and spatial indexes for larger datasets.
