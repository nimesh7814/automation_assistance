# GeoJSON Dashboard API

A small FastAPI backend that powers the Streamlit dashboard in `ui/`. It accepts a GeoJSON file, keeps it in memory for the current browser session, and exposes endpoints to inspect, validate, edit, and export it.

## How it works

Every request must include an `X-Session-ID` header (the UI generates and persists one per browser tab). `functions/session.py` keeps an in-memory `dict` keyed by that header — **each session gets its own independent dataset**, not a single shared global. There is **no database and no user accounts**, so:

- Restarting the API process loses all sessions' data.
- Two different `X-Session-ID` values never see or edit each other's data.
- A session is also dropped automatically if it's idle (no API call at all, not just no upload) for longer than `SESSION_TTL_MINUTES` (default 30). A background sweep (`sweep_idle_sessions` in `functions/session.py`, started from `main.py`'s `lifespan`) checks every 60 seconds and evicts anything past that idle threshold, so memory doesn't grow unbounded with abandoned sessions. Calling any endpoint resets that session's idle timer.

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
docker compose up --build -d api   # first run, or after a code change
docker compose up -d api           # subsequent runs
```

or start the whole stack (API + UI + log viewer) the same way, dropping `api` from the command — see the root [README.md](../README.md) for the full getting-started flow.

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

## What gets checked, in plain terms

Validation is powered by the [`geojson_validator`](https://github.com/chrieke/geojson-validator) package, layered with three custom checks (see `functions/validate_fix.py`). There are two separate validation passes: structure checks happen automatically on upload, geometry checks happen when you call `/validate`.

### On upload (structure checks, always run)

| Check | What it catches |
| --- | --- |
| Valid `type` | The top-level object, each feature, and each geometry must declare a `type` that's actually a real GeoJSON type (`FeatureCollection`, `Feature`, `Polygon`, `MultiPolygon`, etc.). |
| Required fields present | A `Feature` must have `geometry` and `properties`; a `FeatureCollection` must have a `features` array. |
| Coordinate shape | Each coordinate position must have 2–3 numbers (longitude, latitude, optional elevation) — not fewer, not more. |
| Geometry type filter (app-specific, not from the library) | Only `Polygon`/`MultiPolygon` features are kept. Anything else (`Point`, `LineString`, `GeometryCollection`, etc.) is rejected and listed in the upload response, the rest of the file still loads. |

### On `/validate` (geometry checks, run on demand)

| Check | What it catches | Fixable by `/fix`? |
| --- | --- | --- |
| Unclosed ring | A ring's first and last point don't match. | Yes |
| Exterior ring wrong winding | The outer ring isn't counter-clockwise, as RFC 7946 requires. | Yes |
| Interior ring wrong winding | A hole isn't clockwise. | Yes |
| Empty geometry *(custom check)* | `geometry` is `null` or has no coordinates. | Yes — but "fixed" means the feature is deleted, since there's nothing to repair. |
| Fewer than 3 unique points | A degenerate ring that isn't really a polygon. | No — needs to be redrawn or deleted by hand. |
| Hole crosses the boundary | A hole's edge crosses the outer ring instead of being fully inside (or fully outside) it. | No — ambiguous, needs manual fixing. |
| Self-intersecting ring *(custom check)* | The polygon's edges cross themselves (a "bowtie" shape). | No — there's no single obviously-correct fix. |
| Hole entirely outside the boundary *(custom check)* | A hole sits completely outside its own exterior ring. | No — needs manual fixing. |

**The rule of thumb**: anything that's a simple mechanical fix (closing a ring, flipping winding direction, dropping something with literally nothing in it) gets auto-fixed by `/fix`. Anything where there's more than one reasonable way to fix it — a self-crossing shape, a misplaced hole, a near-empty ring — is left for a human to redraw on the Edit tab, because guessing wrong would silently corrupt the data.

### What's deliberately *not* checked

The `geojson_validator` library can also check for coordinates outside the valid longitude/latitude range, geometries crossing the antimeridian (the 180° line), duplicate vertices within a ring, excessive coordinate precision, and excessive vertex counts — none of these are currently turned on in this app (`functions/validate_fix.py`'s `VALIDATOR_CRITERIA` doesn't include them). If you need one of these, it's a one-line addition there.

### CRS (coordinate reference system) — what RFC 7946 says, and what this app actually does

[RFC 7946](https://datatracker.ietf.org/doc/html/rfc7946) (the GeoJSON standard) section 4 is explicit: every GeoJSON coordinate is assumed to be longitude/latitude in WGS84 (`urn:ogc:def:crs:OGC::CRS84`), full stop. The older `crs` member from the 2008 GeoJSON spec was *deliberately removed* in RFC 7946 — the spec says alternative CRSes caused too many interoperability problems, so a fully-compliant GeoJSON file shouldn't carry a `crs` member at all.

In practice, plenty of real-world `.geojson` files (often exported from older GIS tools like QGIS) still include a `crs` member anyway — sometimes pointing at a genuinely different system, like Web Mercator (`EPSG:3857`). `geojson_validator` actually supports flagging this (`validate_structure(..., check_crs=True)` reports a `crs` member as an error), but this app calls it with the default (`check_crs=False`), so **a `crs` member currently passes through completely silently.**

That matters because nothing downstream reprojects coordinates — area calculations (`functions/stats.py`) and the map both just assume every coordinate is already WGS84 lon/lat. If a file's `crs` member says otherwise and the file's actual coordinates aren't WGS84, the app will compute areas and plot positions as if they were, with no warning. Turning on `check_crs=True` would at least flag the presence of a `crs` member; actually reprojecting non-WGS84 coordinates would need `pyproj` transformation logic that doesn't exist yet.

`/fix` attempts to repair the auto-fixable subset of issues above and reports what was fixed and what is still left afterwards.

## Limitations

- **File upload only.** `/upload/file` requires an actual multipart file — there's no endpoint to submit raw GeoJSON text directly in a request body.
- **`.geojson` only.** KML, Shapefile (`.shp`/`.shx`/`.dbf`), and plain `.json` aren't accepted, even if their contents are otherwise valid GeoJSON-shaped data. Supporting those would mean converting them to GeoJSON on upload (e.g. via `fiona`/GDAL for KML and Shapefile) — that conversion step doesn't exist yet, but would be a reasonable thing to add.
- **No CRS detection or reprojection** — see above.

## Logging

Requests and unexpected errors are logged to the console (visible with `docker compose logs api` or via Dozzle — see the root README) and to a rotating file under `LOG_DIR` (default `logs`, bind-mounted to `../logs/api` on the host by `docker-compose.yml`, so they survive container removal/rebuilds, not just restarts). Any error that isn't already a handled `HTTPException` is logged with a full traceback and returns a generic `500` message to the client, so internal details are never leaked to the UI.

## Sample data

A sample farm boundary file is provided at `sample_data/Farm_file.geojson` (repo root) — useful for trying out the upload and the other endpoints.

`test.py` in this folder is a one-off geopandas scratch script with a hardcoded local file path; it is not part of the API and is not a test runner.
