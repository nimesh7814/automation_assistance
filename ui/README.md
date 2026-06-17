# GeoJSON Dashboard UI

A Streamlit dashboard for the API in `../api/`. Upload a GeoJSON file, then walk through validation, duplicate detection, map-based editing, export, and an AI assistant — all scoped to your browser session via a generated `X-Session-ID`.

## Tabs

- **Upload** — drop a `.geojson` file, see which features were accepted/skipped, preview them on a map with a checkbox-driven attribute table.
- **Validate** — run geometry validation (invalid rings, winding, self-intersections, holes) and auto-fix the fixable subset.
- **Duplicates** — scan for identical and spatially-intersecting geometries at an adjustable match threshold, and remove duplicates.
- **Edit** — pan/zoom map with per-feature visibility toggles; draw new polygons or drag vertices of an existing one (edits auto-save), edit attribute properties, delete features.
- **Export** — preview the current feature table and download the session's data as a `.geojson` file.
- **Assistant** — ask questions about the loaded data via a Gemini-powered, read-only function-calling assistant (see `../assistant/README.md`). Hidden behind a `GEMINI_API_KEY` — every other tab works without it.

## Running locally

```bash
cd ui
pip install -r requirements.txt
streamlit run app.py
```

Requires the API to be reachable (default `http://localhost:8000` — set in `.env`, see below). The dashboard opens at `http://localhost:8501`.

## Running with Docker

From the repo root:

```bash
docker compose up --build -d ui   # rebuild/restart just the UI
docker compose logs ui --tail 50
```

`ui/Dockerfile` copies both `ui/` and `../assistant/` into the image, since the Assistant tab imports `assistant` as a sibling package.

## Configuration (`.env`)

Copy `.env.example` to `.env` and fill in:

| Variable | Purpose |
| --- | --- |
| `GEMINI_API_KEY` | Required for the Assistant tab. Without it, that tab shows a notice and the rest of the dashboard works normally. Get a free-tier key at https://aistudio.google.com/apikey. |
| `LIMIT` | Per-session message cap for the assistant (default `100`). |
| `API_BASE_URL` | Where the UI looks for the API. `http://api:8000` under Docker Compose (container-to-container DNS — `localhost` inside the `ui` container is the `ui` container itself), `http://localhost:8000` when running the UI directly on the host. |

`.env` is loaded via `python-dotenv` and is git-ignored — never commit your real key.

## Code layout

- `app.py` — bootstrap only: page config, CSS, logging, session init, sidebar, tab wiring. No tab-rendering logic itself.
- `api_client.py` — `APIError`, the `api_request()` HTTP helper everything goes through, session helpers, `upload_file`, `probe_health`, `refresh_features`, `clear_data`, `require_api_connection`.
- `map_utils.py` — symbology, the pydeck preview map (Upload/Export tabs) and the folium edit map (Edit tab), plus geometry-diff helpers.
- `tabs/{upload,validate,duplicates,edit,export}.py` — one `render_*_tab` function per workflow step.

All tabs share `st.session_state["features"]` as the locally cached copy of whatever the API has for this session — call `refresh_features()` after any change that mutates the backend dataset.

## Logging

Each module gets its own child logger (`geojson_dashboard.ui.*`) logging key actions — uploads, edits, deletes, exports, every `api_request()` call's outcome — to console, visible via `docker compose logs ui`.
