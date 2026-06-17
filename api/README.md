# GeoJSON Dashboard API

A small FastAPI backend that powers the Streamlit dashboard in `ui/`. It accepts a GeoJSON file, keeps it in memory for the current browser session, and exposes endpoints to inspect, validate, edit, and export it.

## How it works

Every request must include an `X-Session-ID` header (the UI generates and persists one per browser tab). `functions/session.py` keeps an in-memory `dict` keyed by that header — **each session gets its own independent dataset**, not a single shared global. There is **no database and no user accounts**, so:

- Restarting the API process loses all sessions' data.
- Two different `X-Session-ID` values never see or edit each other's data.

Only `Polygon` and `MultiPolygon` features are kept. Anything else (points, lines, etc.) is dropped on upload and reported in the upload summary.

Features are identified by their 0-based index in the `features` list, not a stable ID — deleting or reordering shifts every later index.

## Running locally

```bash
cd api
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

The API is then available at `http://localhost:8000`. Interactive docs (Swagger UI) are at `http://localhost:8000/docs`.

## Running with Docker

From the repo root:

```bash
docker compose up --build api
```

or start the whole stack (API + UI) with `docker compose up --build`.

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | Health check (`{"message": "API Connected"}`). |
| `POST` | `/upload/file` | Upload a `.geojson` file (multipart form, field name `file`). |
| `GET` | `/features` | Return all features currently in the session. |
| `GET` | `/stats/area` | Total and per-feature area in hectares. |
| `GET` | `/validate` | Check the geometries for structural and topology issues. |
| `POST` | `/fix` | Try to automatically repair invalid/problematic geometries. |
| `GET` | `/duplicates?remove_duplicates=false&duplicate_threshold=0.99` | Find geometries that are identical to, or spatially intersect, another one. Pass `remove_duplicates=true` to delete the duplicates. |
| `POST` | `/features` | Add a new feature (geometry + properties). |
| `PUT` | `/features/{id}/geometry` | Replace the geometry of a feature. |
| `PUT` | `/features/{id}/properties` | Replace the attribute table (properties) of a feature. |
| `DELETE` | `/features/{id}` | Delete a feature. |
| `GET` | `/export` | Download the current dataset as a `.geojson` file. |
| `DELETE` | `/data` | Clear the session and start over. |

All endpoints (except `/`) require the `X-Session-ID` header. Errors come back in the same shape: `{"message": "...", "errors": [...]}` with an appropriate HTTP status code (e.g. `400` for bad input, `404` if nothing has been uploaded yet for that session). `errors` is a list of details (e.g. which feature had a problem) and is empty when there is nothing extra to report.

## Geometry validation

Validation and auto-fix are powered by the [`geojson_validator`](https://github.com/chrieke/geojson-validator) package, layered with custom checks for empty geometries, self-intersections, and holes lying outside their exterior ring (see `functions/validate_fix.py`). `/validate` reports:

- **Structure issues** — problems with the overall GeoJSON (e.g. CRS), caught at upload time.
- **Geometry issues** — invalid rings, winding direction, self-intersections, holes, etc.

`/fix` attempts to repair the auto-fixable subset of those issues and reports what was fixed and what is still left afterwards.

## Logging

Requests and unexpected errors are logged to the console (visible with `docker compose logs api`). Any error that isn't already a handled `HTTPException` is logged with a full traceback and returns a generic `500` message to the client, so internal details are never leaked to the UI.

## Sample data

A sample farm boundary file is provided at `sample_data/Farm_file.geojson` (repo root) — useful for trying out the upload and the other endpoints.

`test.py` in this folder is a one-off geopandas scratch script with a hardcoded local file path; it is not part of the API and is not a test runner.
