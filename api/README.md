# GeoJSON Dashboard API

A small FastAPI backend that powers the Streamlit dashboard in `ui/`. It accepts a GeoJSON file, keeps it in memory for the current browser session, and exposes endpoints to inspect, validate, edit, and export it. It doesn't know `ui/` exists — everything here is a plain REST API you could drive from `curl`, the auto-generated docs at `/docs`, or any other frontend.

## Architecture

`main.py` is the entire wiring diagram: it creates the FastAPI app, registers CORS and a request-logging middleware, defines two exception handlers that normalize every error response into the same shape, and then maps each route straight onto a function imported from `functions/`. There's no service or repository layer in between — a route handler calls into one `functions/*.py` module, that module reads or writes the session's data via `functions/session.py`, and the result goes straight back as the response body.

A request's life looks like this:

1. **Session resolution.** Every route except `/` depends on `get_session_id` (`functions/session.py`), which reads the `X-Session-ID` header. No header means an immediate `400` — there's no anonymous fallback session.
2. **Route handler.** `main.py` calls the matching function in `functions/` — `upload_geojson`, `validate_geometry`, `detect_duplicates`, and so on — passing the session ID plus whatever the request supplied.
3. **Session storage.** `functions/session.py` holds one in-memory dict (`_sessions`), keyed by session ID, each entry holding the current GeoJSON (`data`), the CRS status from the last upload (`crs`), and a `last_access` timestamp. There's no database; restarting the process drops every session.
4. **Response.** Whatever the function returns is serialized straight to JSON. If it instead raises an `HTTPException`, or FastAPI's own request validation fails, or something throws unexpectedly, one of the handlers below catches it and reshapes it into the same `{"message": ..., "errors": [...]}` contract every other endpoint already uses — callers only ever have to handle one error shape.

A background task, started from `main.py`'s `lifespan` context manager, calls `sweep_idle_sessions()` every 60 seconds and evicts any session that hasn't made a request in `SESSION_TTL_MINUTES` (default 30). This is the only thing that ever removes data on its own — nothing times out a single upload, only a whole abandoned session.

Each module under `functions/` owns one concern and nothing else:

| Module | Owns |
| --- | --- |
| `upload.py` | Parsing and validating an uploaded file end to end — see [the upload pipeline](#what-happens-in-order-when-you-call-post-uploadfile) below. |
| `validate_fix.py` | The `/validate` and `/fix` geometry checks, layered on top of `geojson_validator`. |
| `duplicates.py` | The `/duplicates` scan — see [Duplicates and intersections](#duplicates-and-intersections-how-the-detection-actually-works) below. |
| `stats.py` | Area calculation (`/stats/area`), using `pyproj`'s WGS84 ellipsoid so areas come out in real square metres, not squared degrees. |
| `edit_geometry_attribute.py` | Replacing a feature's geometry or properties, and adding new features. |
| `delete_feature.py` | Deleting a feature by index. |
| `get_feature.py` | Returning everything currently in the session (`/features`). |
| `export.py` | Building the downloadable `.geojson` file. |
| `session.py` | The in-memory store itself, session TTL sweeping, and the shared `check_feature_id` bounds check used by every route that targets one feature by index. |
| `logging.py` | Routes both this app's logs and uvicorn's own through `loguru`, to a console sink and a rotating file. |

One thing worth calling out because it trips people up: **features are identified by their 0-based position in the `features` list, not a stable ID.** Delete feature `2` and feature `3` becomes the new feature `2`. Every endpoint that takes a `feature_id` is really taking a list index, and so is the UI's "Feature #" column — there's no separate ID scheme layered on top.

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
docker compose up --build -d api   # first run, or after a code change
docker compose up -d api           # subsequent runs
```

or start the whole stack (API + UI + log viewer) the same way, dropping `api` from the command — see the root [README.md](../README.md) for the full getting-started flow.

## Endpoints

| Method   | Path                                                           | Description                                                                                                                         |
| -------- | -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `GET`    | `/`                                                            | Health check (`{"message": "API Connected"}`).                                                                                      |
| `POST`   | `/upload/file`                                                 | Upload a `.geojson` file (multipart form, field name `file`). Accepts a `FeatureCollection`, or a bare `Polygon`/`MultiPolygon` (wrapped into a one-feature collection). |
| `GET`    | `/features`                                                    | Return all features currently in the session.                                                                                       |
| `GET`    | `/stats/area`                                                  | Total and per-feature area in hectares.                                                                                             |
| `GET`    | `/validate`                                                    | Check the geometries for structural and topology issues.                                                                            |
| `POST`   | `/fix`                                                         | Try to automatically repair invalid/problematic geometries.                                                                         |
| `GET`    | `/duplicates?remove_duplicates=false&duplicate_threshold=0.99` | Find geometries that are identical to, or spatially intersect, another one. Pass `remove_duplicates=true` to delete the duplicates. |
| `POST`   | `/features`                                                    | Add a new feature (geometry + properties).                                                                                          |
| `PUT`    | `/features/{id}/geometry`                                      | Replace the geometry of a feature.                                                                                                  |
| `PUT`    | `/features/{id}/properties`                                    | Replace the attribute table (properties) of a feature.                                                                              |
| `DELETE` | `/features/{id}`                                               | Delete a feature.                                                                                                                   |
| `GET`    | `/export`                                                      | Download the current dataset as a `.geojson` file.                                                                                  |
| `DELETE` | `/data`                                                        | Clear the session and start over.                                                                                                   |

A bit more detail on each group:

- **`POST /upload/file`** is the only way data gets into a session — there's no endpoint for posting raw GeoJSON text in a request body, only an actual multipart file. It replaces the session's whole dataset rather than merging, so uploading a second file discards the first. See the [upload pipeline](#what-happens-in-order-when-you-call-post-uploadfile) below for exactly what it checks.
- **`GET /features`** and **`GET /stats/area`** are both read-only views over whatever the session currently holds — `/features` for the raw GeoJSON, `/stats/area` for total and per-feature area in hectares (computed geodesically with `pyproj`, so it's accurate even though the underlying coordinates are degrees, not metres).
- **`GET /validate`** and **`POST /fix`** are a pair: `/validate` reports geometry problems without changing anything, `/fix` actually repairs whichever of those problems can be repaired mechanically (closing rings, fixing winding order, dropping truly empty geometries) and reports what's still left afterwards. See [Validation and auto-fix](#validation-and-auto-fix) below.
- **`GET /duplicates`** scans for both exact-ish duplicates and spatial overlaps in one pass; `remove_duplicates=true` turns the scan into a destructive cleanup step. See [Duplicates and intersections](#duplicates-and-intersections-how-the-detection-actually-works) below.
- **`POST /features`**, **`PUT /features/{id}/geometry`**, **`PUT /features/{id}/properties`**, and **`DELETE /features/{id}`** are the hand-editing endpoints behind the Edit tab. All four operate on the same in-memory list by index, and the three that take an `{id}` share one bounds check (`check_feature_id` in `functions/session.py`) so an out-of-range ID always comes back as the same `404` shape no matter which of the three you called.
- **`GET /export`** just serializes the current session back out as a `.geojson` file with a `Content-Disposition: attachment` header, so a browser downloads it instead of rendering it.
- **`DELETE /data`** clears the session's data and CRS status without dropping the session ID itself — the next `/features` call on the same header just comes back empty rather than `404`-ing on a missing session.

All endpoints (except `/`) require the `X-Session-ID` header. Errors come back in the same shape: `{"message": "...", "errors": [...]}` with an appropriate HTTP status code (e.g. `400` for bad input, `404` if nothing has been uploaded yet for that session) — including FastAPI's own request-validation errors (a malformed JSON body, a query parameter out of its allowed range), which are normalized into this same shape rather than FastAPI's default `{"detail": [...]}`. `errors` is a list of details (e.g. which feature had a problem) and is empty when there is nothing extra to report.

## What gets checked, in plain terms

Validation is powered by the [`geojson_validator`](https://github.com/chrieke/geojson-validator) package, layered with three custom checks (see `functions/validate_fix.py`). There are two separate validation passes: structure checks happen automatically on upload, and geometry checks happen when you call `/validate`. The API also includes automatic fixes for the issues that can be repaired safely.

![GeoJSON validation issues and auto-fix support](../assets/validation-issues.svg)

### What happens, in order, when you call `POST /upload/file`

Each step can either stop the upload outright (4xx, nothing is loaded into the session) or just flag/drop individual features and continue. `functions/upload.py` runs them in this order:

| # | Step                                  | Stops the upload entirely?                                                          | Only drops/flags individual features?                                                             |
| - | -------------------------------------- | ------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------- |
| 1 | Decode the file as UTF-8               | Yes — any other encoding (e.g. Latin-1) is rejected with a `400` (`type: "encoding"`). | —                                                                                                      |
| 2 | Parse as JSON / GeoJSON (`geojson.loads`) | Yes — invalid JSON syntax is a `400` (`type: "json"`); a structurally broken document the `geojson` library itself can't construct (e.g. a `FeatureCollection` with no `features` array, coordinates that aren't numbers) is a `400` (`type: "structure"`). | —                                                                                                      |
| 3 | Check the top-level `type`             | Yes — anything other than `FeatureCollection`, `Polygon`, or `MultiPolygon` is a `400` (`type: "filter"`). | A bare `Polygon`/`MultiPolygon` is wrapped into a one-feature `FeatureCollection` and continues normally. |
| 4 | Validate structure (`geojson_validator`) | No                                                                                     | Per-feature problems (missing `type`/`geometry`/`properties`, bad coordinate shape) are reported against that feature's index and the feature is dropped from the loaded set. |
| 5 | Filter geometry type                   | No                                                                                     | Only `Polygon`/`MultiPolygon` features are kept; `Point`, `LineString`, `GeometryCollection`, missing geometry, etc. are dropped and reported. |
| 6 | Check there's at least one accepted feature | Yes — if every feature was dropped by steps 4–5, it's a `400` listing why each one was rejected. | —                                                                                                      |
| 7 | Check the CRS                          | No                                                                                     | A `crs` member naming anything other than WGS84/CRS84 (or its `EPSG:4326` alias) is flagged (`type: "crs"`) in the response and recorded for the session — see [CRS](#crs-coordinate-reference-system--what-rfc-7946-says-and-what-this-app-actually-does) below. The file still loads. |

### Upload response shape

```json
{
  "message": "GeoJSON uploaded successfully.",
  "valid": true,
  "errors": [
    {
      "feature": 1,
      "path": "/features/1",
      "geometry_type": null,
      "type": "structure",
      "message": "Missing 'type' member",
      "properties": { "fid": 2 },
      "value": null
    }
  ],
  "summary": {
    "total_features": 5,
    "selected_features": 4,
    "rejected_features": 1
  },
  "crs": { "present": false, "name": null, "accepted": true, "value": null, "description": "..." },
  "processed_geojson": { "type": "FeatureCollection", "features": [ "...accepted features..." ] }
}
```

`valid` is `false` whenever `errors` is non-empty (skipped features and/or an unsupported CRS) but the upload can still be `200 OK` as long as at least one feature was accepted — only a totally-empty result (step 6 above) is a `400`. Each entry in `errors` always has all seven keys; most are `null` when not applicable for that error's `type` (`encoding`, `json`, `structure`, `coordinate`, `filter`, or `crs`).

### Structure checks (step 4 above, always run on upload)

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

A feature with an empty geometry can't actually come in through `/upload/file` — the upload pipeline's own structure check (step 4 in the [upload pipeline](#what-happens-in-order-when-you-call-post-uploadfile) above) rejects a `Polygon` with no coordinates before it's ever loaded into the session. The only way one ends up in a session today is `POST /features` with a geometry like `{"type": "Polygon", "coordinates": []}`, since that endpoint only checks the geometry's `type`, not its coordinates. `validate_geometry`/`fix_geojson` guard against this case explicitly (`safe_validate_geometries` in `functions/validate_fix.py` swaps it for a placeholder before handing the data to `geojson_validator`, which otherwise raises an unhandled `IndexError` on an empty coordinates list) so it's reported and auto-fixed correctly rather than crashing the request.

### Auto-fix behavior

`POST /fix` handles only issues that can be corrected mechanically without guessing the intended shape:

| Issue key | Auto-fix action |
| --- | --- |
| `unclosed` | Adds the missing closing coordinate to the ring. |
| `exterior_not_ccw` | Rewinds the exterior ring to counter-clockwise order. |
| `interior_not_cw` | Rewinds interior rings or holes to clockwise order. |
| `empty_geometry` | Removes the feature because there is no geometry to repair. |

The following issues are intentionally not auto-fixed because the correct geometry is ambiguous:

| Issue key | Manual action needed |
| --- | --- |
| `less_three_unique_nodes` | Redraw or delete the feature. |
| `inner_and_exterior_ring_intersect` | Repair the exterior ring or hole placement by hand. |
| `self_intersection` | Reshape the polygon so edges no longer cross. |
| `hole_outside` | Move, remove, or redraw the hole inside the exterior boundary. |

`/fix` reports both what was fixed and what is still left afterwards, by re-running the same checks before and after and diffing the two result sets.

### What's deliberately _not_ checked

The `geojson_validator` library can also check for coordinates outside the valid longitude/latitude range (`outside_lat_lon_boundaries` — i.e. longitude outside ±180°, latitude outside ±90°), geometries crossing the antimeridian (`crosses_antimeridian`), duplicate vertices within a ring, excessive coordinate precision, and excessive vertex counts — none of these are currently turned on in this app (`functions/validate_fix.py`'s `VALIDATOR_CRITERIA` doesn't include them, and they're not passed to `geojson_validator.validate_geometries()`'s separate `criteria_problematic` argument either). If you need one of these, it's a one-line addition there.

## CRS (coordinate reference system) — what RFC 7946 says, and what this app actually does

[RFC 7946](https://datatracker.ietf.org/doc/html/rfc7946) (the GeoJSON standard) section 4 is explicit: every GeoJSON coordinate is assumed to be longitude/latitude in WGS84 (`urn:ogc:def:crs:OGC::CRS84`), full stop. The older `crs` member from the 2008 GeoJSON spec was _deliberately removed_ in RFC 7946 — the spec says alternative CRSes caused too many interoperability problems, so a fully-compliant GeoJSON file shouldn't carry a `crs` member at all.

In practice, plenty of real-world `.geojson` files (often exported from older GIS tools like QGIS) still include a `crs` member anyway — sometimes pointing at a genuinely different system, like Web Mercator (`EPSG:3857`). `functions/upload.py` checks for this on every upload against an allow-list (`ALLOWED_CRS`) of names that are equivalent to WGS84 lon/lat for this app's purposes:

- `urn:ogc:def:crs:OGC:1.3:CRS84` — the RFC 7946 CRS, explicitly defined as longitude/latitude order.
- `urn:ogc:def:crs:EPSG::4326` and the shorter `EPSG:4326` — same WGS84 datum as CRS84. EPSG formally defines its axis order as latitude/longitude, but GeoJSON coordinates are always lon/lat regardless of the `crs` member (RFC 7946 §4), and in practice most tools that tag a GeoJSON export `EPSG:4326` mean the same lon/lat data as CRS84 — so this app treats the names as interchangeable rather than rejecting the very common `EPSG:4326` label.

If the file has no `crs` member, or its `crs.properties.name` matches one of the above, the CRS is accepted; anything else (a different EPSG code, a malformed `crs` object, etc.) is flagged as a `crs`-type error in the upload response and the session-wide CRS status (also returned from `GET /features`, so it survives a page reload). The UI reads that status to disable the Validate, Duplicates, Edit, Export, and Assistant tabs with an explicit error until a correctly-projected file is uploaded.

**Flagging is not the same as reprojecting.** Rejected/flagged files still load — the app doesn't transform their coordinates into WGS84, it just refuses to compute areas or plot positions from them until you fix the source file. Area calculations (`functions/stats.py`) and the map both assume every coordinate is already WGS84 lon/lat; there is no `pyproj`-based transformation step. Re-export the file in WGS84/CRS84 (e.g. "reproject" in QGIS) or strip its `crs` member before re-uploading.

**The CRS check only looks at the declared name — it never looks at the coordinates themselves.** A file with no `crs` member (so it's accepted outright, per the rule above) but whose coordinates are actually in a completely different unit — UTM meters, State Plane feet, or anything outside the valid ±180° longitude / ±90° latitude range — passes this check and loads normally, then plots in the wrong place or produces a nonsense area, with no warning at any point. `geojson_validator` ships exactly the check that would catch the out-of-range case (`outside_lat_lon_boundaries`, mentioned in [What's deliberately not checked](#whats-deliberately-not-checked) above), but it isn't wired into the upload pipeline or `/validate` today.

## Duplicates and intersections: how the detection actually works

`GET /duplicates` (`functions/duplicates.py`) answers two genuinely different questions in one pass, and reports both:

**1. Exact-ish duplicates.** Every feature's geometry is parsed with Shapely, gently repaired if invalid (`buffer(0)`, a common trick for fixing minor self-touching issues), and then serialized to a WKT string rounded to a precision derived from `duplicate_threshold` (`int(threshold * 10)` decimal places — so the default `0.99` rounds to roughly 9 decimal places, while a lower threshold rounds more aggressively and catches near-matches that aren't pixel-perfect). Any two features whose rounded WKT strings are identical are duplicates of each other; the first occurrence is kept, every later one in the group is flagged. This is intentionally a simple, exact-string comparison rather than a fuzzy geometric similarity score — it's fast and predictable, at the cost of missing duplicates that are topologically identical but wound or ordered differently (see [Limitations](#limitations)).

**2. Spatial intersections.** Separately, every pair of (non-duplicate) geometries is tested for a real overlap with Shapely's `intersects`/`intersection`. This is a different signal from duplication — two distinct, legitimate plots can still overlap, and that's worth surfacing on its own. Overlapping pairs are clustered together with a small union-find (disjoint-set) structure, so if features 2, 5, and 9 all mutually overlap, they're reported as one intersection group of three rather than three separate pairs. Group numbers and pair details (which two features, and the overlap area) are both included in the response.

Passing `remove_duplicates=true` turns the read-only scan into a cleanup step: every feature flagged as a duplicate is removed, the remaining features are re-numbered to close the gap (since IDs are just list positions), and the intersection groups are recomputed against what's left — so the response reflects the dataset *after* removal, not before. Intersections themselves are never auto-removed by this endpoint; only exact-ish duplicates are, since two overlapping-but-distinct shapes are a judgment call a human should make.

## Limitations

- **File upload only.** `/upload/file` requires an actual multipart file — there's no endpoint to submit raw GeoJSON text directly in a request body.
- **One file at a time.** `/upload/file` replaces the session's whole dataset (`set_dataset` overwrites, it doesn't merge) — uploading a second file discards the first rather than combining them. Loading several client files into one working set isn't supported yet.
- **File extension isn't enforced by the API.** `/upload/file` only checks that the content parses as GeoJSON-shaped JSON — it accepts any filename/extension, including a `.txt` or `.json` file that happens to contain valid GeoJSON. The Streamlit uploader restricts the file picker to `.geojson` client-side, but that's a UX nicety, not a server-side guarantee. KML and Shapefile (`.shp`/`.shx`/`.dbf`) content still won't parse as JSON and will be rejected as malformed, since there's no conversion step (e.g. via `fiona`/GDAL) for those formats.
- **CRS is flagged, not reprojected.** Uploads with a `crs` member outside the accepted WGS84 aliases are detected and block the rest of the app from trusting that session's data (see above) — but the app cannot transform non-WGS84 coordinates into WGS84 itself. The only fix today is re-exporting the source file in WGS84/CRS84.
- **Coordinate values aren't range-checked.** Neither the upload CRS check nor `/validate` verifies that coordinates actually fall within ±180° longitude / ±90° latitude. A file that passes the CRS check (e.g. it has no `crs` member at all) but holds out-of-range or wrongly-scaled coordinates loads and looks fine, then plots in the wrong place or computes a meaningless area with no warning. `geojson_validator`'s `outside_lat_lon_boundaries` check could close this gap if it were turned on.
- **In-memory sessions only.** Session data lives in a Python dictionary. It is fast and simple for a demo or internal QA tool, but restarting the API loses all uploaded data. Production use would need persistent storage such as PostGIS, PostgreSQL JSONB, object storage, or another database-backed session store.
- **No authentication or authorization.** The API trusts whoever can reach it. In production it should sit behind SSO or Cloudflare Access, and the API itself should still enforce authorization instead of relying only on the network edge.
- **Feature IDs are not stable.** Endpoints use the feature's current list index. Deleting feature `2` shifts every later feature ID. A production version should assign stable UUIDs and keep those IDs through edits and exports.
- **Duplicate detection is exact, not fuzzy.** Duplicates are detected by rounded WKT strings generated from Shapely geometries. This works for exact or very similar coordinate sequences, but topology-equivalent shapes with different vertex ordering, ring ordering, or small coordinate differences may not always be grouped as expected. A stronger implementation would normalize geometries (consistent ring start point and winding) before comparing, and use a real similarity metric instead of string equality.
- **Intersection detection is pairwise.** The current implementation compares each geometry to each other geometry — O(n²) — which is fine for small and medium files, but large datasets should use an R-tree or another spatial index to avoid comparing every pair.
- **Geometry updates are type-checked, not fully validated.** `PUT /features/{id}/geometry` requires `Polygon` or `MultiPolygon` and coordinates, but it does not run the full validation suite before saving. Users should run `/validate` after manual geometry JSON edits.
- **Attribute schemas are flexible.** Properties can differ by feature and there is no required schema. That is convenient for mixed farm datasets, but production teams may want required fields, data types, controlled vocabularies, and validation rules.
- **No audit trail.** Edits, fixes, and duplicate removals are logged as events, but the API does not keep a reversible history of dataset versions. Production use should add versioning, before/after diffs, and user identity in the audit log.

## Logging

Requests and unexpected errors are logged to the console (visible with `docker compose logs api` or via Dozzle — see the root README) and to a rotating file under `LOG_DIR` (default `logs`, bind-mounted to `../logs/api` on the host by `docker-compose.yml`, so they survive container removal/rebuilds, not just restarts). Any error that isn't already a handled `HTTPException` is logged with a full traceback and returns a generic `500` message to the client, so internal details are never leaked to the UI.
