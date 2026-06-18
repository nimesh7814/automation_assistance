# GeoJSON Viewer API

A FastAPI backend that powers the Streamlit dashboard in `ui/`. It accepts a GeoJSON file, keeps it in memory for the current browser session, and exposes endpoints to inspect, validate, edit, and export it.

## Architecture

`main.py` is the entire wiring diagram: it creates the FastAPI app, registers CORS and a request-logging middleware, defines two exception handlers that normalize every error response into the same shape, and then maps each route straight onto a function imported from `functions/`. There's no service or repository layer in between, a route handler calls into one `functions/*.py` module, that module reads or writes the session's data via `functions/session.py`, and the result goes straight back as the response body.

A background task, started from `main.py`'s `lifespan` context manager, calls `sweep_idle_sessions()` every 60 seconds and evicts any session that hasn't made a request in `SESSION_TTL_MINUTES` (default 30). This is the only thing that ever removes data on its own — nothing times out a single upload, only a whole abandoned session.

Each module under `functions/` owns one concern and nothing else:

| Module                       | Owns                                                                                                                                                    |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `upload.py`                  | Parsing and validating an uploaded file end to end, see [the upload pipeline](#what-happens-in-order-when-you-call-post-uploadfile) below.              |
| `validate_fix.py`            | The `/validate` and `/fix` geometry checks, layered on top of `geojson_validator`.                                                                      |
| `duplicates.py`              | The `/duplicates` scan, see [Duplicates and intersections](#duplicates-and-intersections-how-the-detection-actually-works) below.                       |
| `stats.py`                   | Area calculation (`/stats/area`), using `pyproj`'s WGS84 ellipsoid so areas come out in square metres, not squared degrees.                             |
| `edit_geometry_attribute.py` | Replacing a feature's geometry or properties, and adding new features.                                                                                  |
| `delete_feature.py`          | Deleting a feature by index.                                                                                                                            |
| `get_feature.py`             | Returning everything currently in the session (`/features`).                                                                                            |
| `export.py`                  | Building the downloadable `.geojson` file.                                                                                                              |
| `session.py`                 | The in-memory store itself, session TTL sweeping, and the shared `check_feature_id` bounds check used by every route that targets one feature by index. |
| `logging.py`                 | Routes both this app's logs and uvicorn's own through `loguru`, to a console sink and a rotating file.                                                  |

## How sessions work

Every request must include an `X-Session-ID` header (the UI generates and persists one per browser tab). `functions/session.py` keeps an in-memory `dict` keyed by that header — **each session gets its own independent dataset**, not a single shared global. There is **no database and no user accounts**, so:

- Restarting the API process loses all sessions' data.
- Two different `X-Session-ID` values never see or edit each other's data.
- A session is also dropped automatically if it's idle (no API call at all, not just no upload) for longer than `SESSION_TTL_MINUTES` (default 30). Calling any endpoint resets that session's idle timer.

Only `Polygon` and `MultiPolygon` features are kept. Anything else (points, lines, etc.) is dropped on upload and reported in the upload response.

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
# first run, or after a code change
docker compose up --build -d api

# subsequent runs
docker compose up -d api
```

or start the whole stack (API + UI + log viewer) the same way, dropping `api` from the command — see the root [README.md](../README.md) for the full getting-started flow.

## Endpoints

| Method   | Path                                                       | Description                                                                                                                                                              |
| -------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `GET`    | `/`                                                        | Health check (`{"message": "API Connected"}`).                                                                                                                           |
| `POST`   | `/upload/file`                                             | Upload a `.geojson` file (multipart form, field name `file`). Accepts a `FeatureCollection`, or a bare `Polygon`/`MultiPolygon` (wrapped into a one-feature collection). |
| `GET`    | `/features`                                                | Return all features currently in the session.                                                                                                                            |
| `GET`    | `/stats/area`                                              | Total and per-feature area in hectares.                                                                                                                                  |
| `GET`    | `/validate`                                                | Check the geometries for structural and topology issues.                                                                                                                 |
| `POST`   | `/fix`                                                     | Try to automatically repair invalid/problematic geometries.                                                                                                              |
| `GET`    | `/duplicates?remove_duplicates=false&duplicate_threshold=` | Find geometries that are identical to, or spatially intersect, another one. Pass `remove_duplicates=true` to delete the duplicates.                                      |
| `POST`   | `/features`                                                | Add a new feature (geometry + properties).                                                                                                                               |
| `PUT`    | `/features/{id}/geometry`                                  | Replace the geometry of a feature.                                                                                                                                       |
| `PUT`    | `/features/{id}/properties`                                | Replace the attribute table (properties) of a feature.                                                                                                                   |
| `DELETE` | `/features/{id}`                                           | Delete a feature.                                                                                                                                                        |
| `GET`    | `/export`                                                  | Download the current dataset as a `.geojson` file.                                                                                                                       |
| `DELETE` | `/data`                                                    | Clear the session and start over.                                                                                                                                        |

All endpoints (except `/`) require the `X-Session-ID` header.

## What gets checked?

Validation is done by the [`geojson_validator`](https://github.com/chrieke/geojson-validator) package, layered with three custom checks (see `functions/validate_fix.py`). There are two separate validation passes: structure checks happen automatically on upload, and geometry checks happen when you call `/validate`. The API also includes automatic fixes for the issues that can be repaired safely.

![GeoJSON validation issues and auto-fix support](../assets/validation-issues.svg)

### What happens, in order, when you call `POST /upload/file`

Each step can either stop the upload outright (nothing is loaded into the session) or just flag/drop individual features and continue. `functions/upload.py` runs them in this order:

| #   | Step                                        | Stops the upload entirely?                                                                                                                                                                                                                                  | Only drops/flags individual features?                                                                                                                                         |
| --- | ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Decode the file as UTF-8                    | Yes — any other encoding (e.g. Latin-1) is rejected with a `400` (`type: "encoding"`).                                                                                                                                                                      | —                                                                                                                                                                             |
| 2   | Parse as JSON / GeoJSON (`geojson.loads`)   | Yes — invalid JSON syntax is a `400` (`type: "json"`); a structurally broken document the `geojson` library itself can't construct (e.g. a `FeatureCollection` with no `features` array, coordinates that aren't numbers) is a `400` (`type: "structure"`). | —                                                                                                                                                                             |
| 3   | Check the top-level `type`                  | Yes — anything other than `FeatureCollection`, `Polygon`, or `MultiPolygon` is a `400` (`type: "filter"`).                                                                                                                                                  | A bare `Polygon`/`MultiPolygon` is wrapped into a one-feature `FeatureCollection` and continues normally.                                                                     |
| 4   | Validate structure (`geojson_validator`)    | No                                                                                                                                                                                                                                                          | Per-feature problems (missing `type`/`geometry`/`properties`, bad coordinate shape) are reported against that feature's index and the feature is dropped from the loaded set. |
| 5   | Filter geometry type                        | No                                                                                                                                                                                                                                                          | Only `Polygon`/`MultiPolygon` features are kept; `Point`, `LineString`, `GeometryCollection`, missing geometry, etc. are dropped and reported.                                |
| 6   | Check there's at least one accepted feature | Yes — if every feature was dropped by steps 4–5, it's a `400` listing why each one was rejected.                                                                                                                                                            | —                                                                                                                                                                             |
| 7   | Check the CRS                               | No                                                                                                                                                                                                                                                          | A `crs` member naming anything other than WGS84/CRS84 (or its `EPSG:4326` alias) is flagged (`type: "crs"`) in the response and recorded for the session                      |

### Structure checks

| Check                                                     | What it catches                                                                                                                                                                                     |
| --------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Valid `type`                                              | The top-level object, each feature, and each geometry must declare a `type` that's actually a real GeoJSON type (`FeatureCollection`, `Feature`, `Polygon`, `MultiPolygon`, etc.).                  |
| Required fields present                                   | A `Feature` must have `geometry` and `properties`; a `FeatureCollection` must have a `features` array.                                                                                              |
| Coordinate shape                                          | Each coordinate position must have 2–3 numbers (longitude, latitude, optional elevation) — not fewer, not more.                                                                                     |
| Geometry type filter (app-specific, not from the library) | Only `Polygon`/`MultiPolygon` features are kept. Anything else (`Point`, `LineString`, `GeometryCollection`, etc.) is rejected and listed in the upload response, the rest of the file still loads. |

## Validation and auto-fix

### On `/validate` (geometry checks, run on demand)

| Check                                               | What it catches                                                                           | Fixable by `/fix`?                                                               |
| --------------------------------------------------- | ----------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Unclosed ring                                       | A ring's first and last point don't match.                                                | Yes                                                                              |
| Exterior ring wrong winding                         | The outer ring isn't counter-clockwise, as RFC 7946 requires.                             | Yes                                                                              |
| Interior ring wrong winding                         | A hole isn't clockwise.                                                                   | Yes                                                                              |
| Empty geometry _(custom check)_                     | `geometry` is `null` or has no coordinates.                                               | Yes — but "fixed" means the feature is deleted, since there's nothing to repair. |
| Fewer than 3 unique points                          | A degenerate ring that isn't really a polygon.                                            | No — needs to be redrawn or deleted by hand.                                     |
| Hole crosses the boundary                           | A hole's edge crosses the outer ring instead of being fully inside (or fully outside) it. | No — ambiguous, needs manual fixing.                                             |
| Self-intersecting ring _(custom check)_             | The polygon's edges cross themselves (a "bowtie" shape).                                  | No — there's no single obviously-correct fix.                                    |
| Hole entirely outside the boundary _(custom check)_ | A hole sits completely outside its own exterior ring.                                     | No — needs manual fixing.                                                        |

**The rule of thumb**: anything that's a simple mechanical fix (closing a ring, flipping winding direction, dropping something with literally nothing in it) gets auto-fixed by `/fix`. Anything where there's more than one reasonable way to fix it — a self-crossing shape, a misplaced hole, a near-empty ring — is left for a human to redraw on the Edit tab, because guessing wrong would silently corrupt the data.

### Auto-fix behavior

`POST /fix` handles only issues that can be corrected mechanically without guessing the intended shape:

| Issue key          | Auto-fix action                                             |
| ------------------ | ----------------------------------------------------------- |
| `unclosed`         | Adds the missing closing coordinate to the ring.            |
| `exterior_not_ccw` | Rewinds the exterior ring to counter-clockwise order.       |
| `interior_not_cw`  | Rewinds interior rings or holes to clockwise order.         |
| `empty_geometry`   | Removes the feature because there is no geometry to repair. |

The following issues are intentionally not auto-fixed because the correct geometry is ambiguous:

| Issue key                           | Manual action needed                                           |
| ----------------------------------- | -------------------------------------------------------------- |
| `less_three_unique_nodes`           | Redraw or delete the feature.                                  |
| `inner_and_exterior_ring_intersect` | Repair the exterior ring or hole placement by hand.            |
| `self_intersection`                 | Reshape the polygon so edges no longer cross.                  |
| `hole_outside`                      | Move, remove, or redraw the hole inside the exterior boundary. |

`/fix` reports both what was fixed and what is still left afterwards, by re-running the same checks before and after and diffing the two result sets.

## CRS (coordinate reference system)

[RFC 7946](https://datatracker.ietf.org/doc/html/rfc7946) (the GeoJSON standard) section 4 is explicit: every GeoJSON coordinate is assumed to be longitude/latitude in WGS84 (`urn:ogc:def:crs:OGC::CRS84`). The older `crs` member from the 2008 GeoJSON spec was _deliberately removed_ in RFC 7946.

If the file has no `crs` member, or its `crs.properties.name` matches one of the above, the CRS is accepted; anything else (a different EPSG code, a malformed `crs` object, etc.) is flagged as a `crs`-type error in the upload response and the session-wide CRS status (also returned from `GET /features`, so it survives a page reload). The UI reads that status to disable the Validate, Duplicates, Edit, Export, and Assistant tabs with an explicit error until a correctly-projected file is uploaded.

## Duplicates and intersections: how the detection actually works

`GET /duplicates` (`functions/duplicates.py`) answers two genuinely different questions in one pass, and reports both:

**1. Exact duplicates.** Every feature's geometry is parsed with Shapely, gently repaired if invalid (`buffer(0)`), and then serialized to a WKT string rounded to a precision derived from `duplicate_threshold` (`int(threshold * 10)` decimal places — so the default `0.99` rounds to roughly 9 decimal places, while a lower threshold rounds more aggressively and catches near-matches that aren't pixel-perfect).

**2. Spatial intersections.** Separately, every pair of geometries is tested for a overlap with Shapely's `intersects`/`intersection`.

Passing `remove_duplicates=true` turns the read-only scan into a cleanup step: every feature flagged as a duplicate is removed, the remaining features are re-numbered.
