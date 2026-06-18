# GeoJSON Dashboard

**Live demo:** [http://geojson.akalanka.me](http://geojson.akalanka.me)

This is a small tool for cleaning up GeoJSON polygon data — the kind of file you get when farm boundaries, land parcels, or any other area-based dataset gets exported out of QGIS, ArcGIS, or a GPS survey tool. Upload a `.geojson` file, see it on a map and in a table, find and fix the geometry problems that quietly break GIS pipelines (self-intersecting rings, holes sitting outside their boundary, duplicate or overlapping shapes), edit it by hand, and export the cleaned result. A Gemini-powered assistant tab lets you ask plain-English questions about whatever's currently loaded, without ever being able to change the data itself.

There's no database and no login. Each browser tab gets its own private, in-memory workspace on the API, identified by a header (`X-Session-ID`) that the UI generates and keeps in the page URL. Close the tab and come back, and it picks up where you left off — until the session sits idle for 30 minutes (configurable via `SESSION_TTL_MINUTES`), at which point the API quietly drops it so abandoned sessions don't grow memory forever.

## How the pieces fit together

| Folder       | What it is                | Default URL           | README                                     |
| ------------ | -------------------------- | ---------------------- | ------------------------------------------- |
| `api/`       | FastAPI backend            | http://localhost:8000  | [api/README.md](api/README.md)             |
| `ui/`        | Streamlit dashboard         | http://localhost:8501  | [ui/README.md](ui/README.md)               |
| `assistant/` | Gemini-based AI assistant   | rendered inside `ui/`  | [assistant/README.md](assistant/README.md) |

Three things actually run:

- **`api/`** is a FastAPI backend that does all the real work — parsing uploads, validating geometry, computing areas, detecting duplicates, applying edits, building exports — and exposes it as a small REST API. It has no idea Streamlit exists; it would sit behind any frontend, or none at all (it's perfectly usable from `/docs` or `curl`).
- **`ui/`** is a Streamlit app and, today, the only frontend that exists. It's a thin client: almost every button click turns into an HTTP call to the API, and the UI's job is mostly to render whatever comes back, or show a clear error when something doesn't.
- **`assistant/`** is a small Gemini-powered chat agent, rendered as the UI's last tab. It's kept deliberately on a short leash — it can only call a fixed set of read-only tools and is incapable of editing, fixing, or deleting data, by construction rather than by convention. See [assistant/README.md](assistant/README.md) for how that's enforced and how it avoids hallucinating answers.

A fourth piece, **Dozzle** (the `logs` service in `docker-compose.yml`), gives you a live web view of the `api` and `ui` containers' logs without having to dig through Docker's CLI — see [Logs](#logs) below.

## Coordinate reference systems

GeoJSON's own spec ([RFC 7946](https://datatracker.ietf.org/doc/html/rfc7946)) is unambiguous: every coordinate is longitude/latitude in WGS84, full stop — there's no field for "and this one's in a different projection." In practice, though, plenty of real-world `.geojson` exports still carry an old-style `crs` member pointing at something else (Web Mercator, a UTM zone, whatever the source GIS tool defaulted to).

This app checks for that on every upload. If the file has no `crs` member, or it names WGS84 under either of its two common aliases (`OGC:CRS84` or `EPSG:4326`), the file is accepted as-is. Anything else gets flagged — and flagging has teeth: the moment a CRS problem is detected, the Validate, Duplicates, Edit, Export, and Assistant tabs all refuse to run until it's fixed, because every area calculation and every pixel on the map assumes the coordinates are already WGS84 lon/lat. Trusting a different projection's raw numbers would silently produce wrong areas and wrong positions, not an obvious crash, which is the worse failure mode.

What it deliberately does **not** do is reproject anything on the fly. There's no transformation step that takes a Web Mercator file and rewrites its coordinates into WGS84 for you — the app can tell you the file is in the wrong system, but fixing it means re-exporting from the source tool in WGS84/CRS84 (or running it through something like `ogr2ogr`) and re-uploading. See [api/README.md](api/README.md#crs-coordinate-reference-system--what-rfc-7946-says-and-what-this-app-actually-does) for exactly which CRS names are accepted and why two different-looking names are treated as the same thing.

## What happens when you upload a file

A `.geojson` upload goes through a short pipeline before anything lands in your session: the file has to decode as UTF-8 and parse as JSON, its top-level `type` has to be a `FeatureCollection` (or a bare `Polygon`/`MultiPolygon`, which gets wrapped into a one-feature collection automatically), each feature is structurally validated and then filtered down to `Polygon`/`MultiPolygon` only, and finally the CRS is checked. Anything that fails early (bad encoding, broken JSON, an unrecognized top-level type, or literally zero usable features) stops the whole upload with a clear error. Anything that fails later — one bad feature among many, or an unsupported CRS — is reported but doesn't block the rest of the file from loading.

The full step-by-step table, with exactly which checks are fatal versus which just drop or flag individual features, what the response JSON looks like, and what the seven fields on every error entry mean, lives in [api/README.md](api/README.md#what-happens-in-order-when-you-call-post-uploadfile) — this is just the short version.

## Validation checks and auto-fix support

The Validate tab checks for ring closure, winding order, weak polygon rings, holes crossing or sitting outside the exterior boundary, self-intersections, and empty geometries. Simple mechanical issues can be auto-fixed; ambiguous geometry problems are reported for manual editing instead, because guessing wrong would silently corrupt the shape.

![GeoJSON validation issues and auto-fix support](assets/validation-issues.svg)

Auto-fixable issues:

- `unclosed`: closes the polygon ring.
- `exterior_not_ccw`: rewinds the exterior ring to counter-clockwise.
- `interior_not_cw`: rewinds hole rings to clockwise.
- `empty_geometry`: removes features that have no usable geometry.

Manual-fix issues:

- `less_three_unique_nodes`: redraw or delete the degenerate polygon.
- `inner_and_exterior_ring_intersect`: manually repair the hole or exterior ring.
- `self_intersection`: manually reshape the crossing polygon.
- `hole_outside`: move, remove, or redraw the misplaced hole.

## Duplicates and intersections

The Duplicates tab is really answering two different questions about the same dataset:

1. **Are any two features literally the same shape?** Every geometry gets rounded to a precision controlled by the "duplicate match threshold" slider and turned into a WKT string; any two features that round to an identical string are flagged as duplicates of each other. A higher threshold rounds less aggressively, so shapes have to match more closely before they count.
2. **Do any features overlap, even if they're not duplicates?** This is a separate, equally useful question — two genuinely different plots overlapping is worth flagging on its own. Every pair of geometries is checked for a real spatial intersection, and overlapping features are clustered together (so three mutually-overlapping shapes show up as one group of three, not three separate pairs, courtesy of a small union-find structure under the hood).

You can remove detected duplicates with one click and the remaining features get re-numbered to close the gap. Intersections are only ever reported, never auto-removed — two overlapping but distinct shapes might both be legitimate data, so that call is left to a human. See [api/README.md](api/README.md#duplicates-and-intersections-how-the-detection-actually-works) for the algorithm in more detail.

## Getting started

### 1. Get the code

Repository: [nimesh7814/automation_assistance.git](https://github.com/nimesh7814/automation_assistance.git)

```bash
git clone https://github.com/nimesh7814/automation_assistance.git
cd automation_assistance
```

### 2. Get a free Gemini API key (optional)

Only needed for the Assistant tab — every other tab works fine without it.

1. Go to https://aistudio.google.com/apikey and sign in with a Google account.
2. Click "Create API key" and copy it (it's free on the tier this app needs).
3. Copy the example env file and paste your key in:

   ```bash
   cp ui/.env.example ui/.env
   ```

   Then open `ui/.env` and set:

   ```
   GEMINI_API_KEY=paste-your-key-here
   ```

   Skip this step entirely if you don't want the Assistant tab — the rest of the dashboard works normally either way.

### 3. Run it

**Option A — Docker install and run (recommended):**

Install Docker Desktop first:

- Windows/macOS: https://www.docker.com/products/docker-desktop/
- Linux: install Docker Engine and Docker Compose from your distribution or Docker's official docs.

Then run the application from the project root:

```bash
# Run the application in detached mode
docker compose up -d

# Tear it down again
docker compose down -v
```

| Service | URL                   | Notes                                      |
| ------- | --------------------- | ------------------------------------------- |
| UI      | http://localhost:8501 | main dashboard                             |
| API     | http://localhost:8000 | docs at `/docs`                            |
| Logs    | http://localhost:8888 | live view of the `api`/`ui` container logs |

**Option B — without Docker (two terminals, run side by side):**

Open terminal 1 for the API:

```bash
cd api
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Open terminal 2 for the UI:

```bash
cd ui
pip install -r requirements.txt
streamlit run app.py
```

Start the API first — the UI works even if the API is briefly unreachable (it shows an "API offline" badge and a retry button), but nothing useful happens until the API is actually up. When running this way, `ui/.env`'s `API_BASE_URL` should be `http://localhost:8000` (it's only `http://api:8000` under Docker Compose, where `api` is the other container's hostname).

## Logs

`docker compose up` also starts a [Dozzle](https://dozzle.dev/) container giving a live web view of the `api` and `ui` container logs at http://localhost:8888 — no setup needed, it reads directly from the Docker daemon (mounted read-only) and is filtered to just this project's containers.

Logs are also written to a rotating file per service (`api.log` / `ui.log`, 5 MB x 3 backups), bind-mounted to `./logs/api` and `./logs/ui` on the host via `docker-compose.yml`, so they're available as plain files and survive `docker compose down`/rebuilds, not just restarts.

## Limitations

- **No on-the-fly reprojection.** The app only trusts WGS84/CRS84 (and its `EPSG:4326` alias) coordinates. A file declaring a different CRS gets flagged and blocks the rest of the app from working with it, but nothing transforms the coordinates for you — see [Coordinate reference systems](#coordinate-reference-systems) above.
- **The CRS check doesn't validate the coordinates themselves.** It only looks at the declared `crs` name, not whether the actual longitude/latitude values are even in range (±180°/±90°). A file with no `crs` member but coordinates in the wrong unit entirely (UTM meters, for instance) will pass and then plot or compute area incorrectly with no warning — see [api/README.md](api/README.md#crs-coordinate-reference-system--what-rfc-7946-says-and-what-this-app-actually-does) for detail.
- **The UI isn't responsive.** It's built and tested for a normal desktop browser window. The map, tables, and tab layout aren't optimized for small screens or mobile, and will likely look cramped or break on one.
- **Complex geometries are hard to edit visually, and slow to edit in general.** A `MultiPolygon` with more than one part isn't reliably reshapeable by dragging vertices on the Edit tab's map — use the JSON geometry editor instead — and any map-based edit round-trips through the API and re-renders the whole page, which is noticeably slower than a native map editor. See [ui/README.md](ui/README.md#limitations) for detail.
- **No persistence.** All data lives in memory per browser session; restarting the API, or letting a session sit idle past `SESSION_TTL_MINUTES`, clears it for good.
- **No authentication.** Anyone who can reach the API or UI can use it — there's no login or per-user access control.
- **One dataset per session.** Uploading a second file replaces the first rather than merging the two; there's no way to combine multiple uploads into one working set.
