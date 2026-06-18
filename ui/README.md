# GeoJSON Viewer UI

A Streamlit dashboard for the API in `../api/`. Upload a GeoJSON file, walk through validation and duplicate detection, inspect the data on maps and tables, edit features, export the cleaned result, and use the Assistant tab to ask grounded questions about the loaded data.

The UI uses a generated `X-Session-ID` so each browser session talks to its own backend dataset.

## How it's built

`app.py` is a bootstrap file and nothing more — it sets the page config, injects a small CSS block (mostly to recolor the primary/download buttons green and the delete button red), wires up logging, sets up the session ID, renders the sidebar, and lays out the six tabs. It has no rendering logic of its own; every tab is one `render_*_tab` function imported from `tabs/`, and `app.py`'s only real job per tab is to re-read `st.session_state["features"]` before handing it to the next one, so a mutation in an earlier tab (say, a delete on the Edit tab... though Edit is actually the fourth tab here) is visible to the ones after it in the same script run.

Everything below `app.py` is split by concern:

- **`api_client.py`** is the one place that talks to the API.
- **`map_utils.py`** holds everything map- and table-related.
- **`tabs/*.py`** is one `render_*_tab` function per workflow step — `upload.py`, `validate.py`, `duplicates.py`, `edit.py`, `export.py`, each importing only what it needs from the two modules above.

All tabs share one piece of state, `st.session_state["features"]`, as the locally cached copy of whatever the API currently holds for this session.

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

- **Responsiveness of UI:** UI can be slow when moving between tabs and when starting.
- **Cannot modify existing Geometry:** Users cannot edit/modify existing geometry of features. The backend facilitate the endpoint, but frontend doesn't support that feature.
- **Complex Geometries:** When a file has many vertices and features, it becomes slow to map.
- **No undo button.** Deletes, duplicate removals, saved attributes, and saved geometry edits update the active API session immediately. No way to undo a edit.
- **Single active dataset.** The UI does not compare two files side by side, merge multiple uploads, or preserve per-file provenance after upload.

## Useful Improvements To Add Next

- Make the layout responsive.
- Add multi-file upload with merge rules and source-file tracking.
- Add undo/version history for edits, auto-fixes, and duplicate removals.
- Add stable feature IDs so deleting one feature does not shift later IDs.
- Add table-level bulk editing for common attribute cleanup tasks.
- Add CRS reprojection (e.g. via `pyproj`) instead of only flagging non-WGS84 files.
- Add background jobs, progress indicators, pagination, and spatial indexes for larger datasets.
