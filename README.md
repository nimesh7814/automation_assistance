# GeoJSON Dashboard

**Live demo:** [http://geojson.akalanka.me](http://geojson.akalanka.me)

A dashboard for working with GeoJSON polygon data: upload a file, view it on a map and in a table, check for problems (invalid/duplicate geometries, unsupported coordinate reference systems), edit it, export the result, and ask a Gemini-powered assistant questions about the loaded data.

Two services, no database, no auth — each browser session gets its own in-memory dataset on the API, scoped by an `X-Session-ID` header. A session's data is dropped automatically after 30 minutes of inactivity (configurable via `SESSION_TTL_MINUTES`) so abandoned sessions don't grow memory unbounded.

| Folder       | What it is                | Default URL                             | README                                     |
| ------------ | ------------------------- | --------------------------------------- | ------------------------------------------ |
| `api/`       | FastAPI backend           | http://localhost:8000 (docs at `/docs`) | [api/README.md](api/README.md)             |
| `ui/`        | Streamlit dashboard       | http://localhost:8501                   | [ui/README.md](ui/README.md)               |
| `assistant/` | Gemini based AI assistant | imported by `ui/app.py`                 | [assistant/README.md](assistant/README.md) |

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

**Option A — Docker install and run (Recommended):**

Install Docker Desktop first:

- Windows/macOS: https://www.docker.com/products/docker-desktop/
- Linux: install Docker Engine and Docker Compose from your distribution or Docker's official docs.

Then run the application from the project root:

```bash
# Run the Application detached mode
docker compose up -d

# Remove the Application
docker compose down -v
```

| Service | URL                   | Notes                                      |
| ------- | --------------------- | ------------------------------------------ |
| UI      | http://localhost:8501 | main dashboard                             |
| API     | http://localhost:8000 | docs at `/docs`                            |
| Logs    | http://localhost:8888 | live view of the `api`/`ui` container logs |

**Option B — without Docker (run each service yourself in two terminals):**

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

- **No reprojection.** The app only works with WGS84/CRS84 coordinates. If an uploaded file declares a different coordinate reference system (e.g. `EPSG:3857`), the API flags it on upload and the UI blocks Validate, Duplicates, Edit, Export, and Assistant with an explicit error — it does not transform the coordinates for you. Re-export the file in WGS84/CRS84 and re-upload it. See [api/README.md](api/README.md#crs-coordinate-reference-system--what-rfc-7946-says-and-what-this-app-actually-does) for details.
- **No persistence.** All data lives in memory per browser session; restarting the API or letting a session sit idle past `SESSION_TTL_MINUTES` clears it.
- **No authentication.** Anyone who can reach the API or UI can use them — there's no login or per-user access control.
