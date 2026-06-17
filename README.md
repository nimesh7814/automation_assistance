# GeoJSON Dashboard

**Live demo:** [http://geojson.akalanka.me](http://geojson.akalanka.me)

A small dashboard for working with GeoJSON polygon data: upload a file, view it on a map and in a table, check for problems (invalid/duplicate geometries), edit it, export the result, and ask a Gemini-powered assistant questions about the loaded data.

Two services, no database, no auth — each browser session gets its own in-memory dataset on the API, scoped by an `X-Session-ID` header. A session's data is dropped automatically after 30 minutes of inactivity (configurable via `SESSION_TTL_MINUTES`) so abandoned sessions don't grow memory unbounded.

| Folder       | What it is                                                       | Default URL                             | README                          |
| ------------ | ----------------------------------------------------------------- | ---------------------------------------- | -------------------------------- |
| `api/`       | FastAPI backend — upload, validate, edit, export                  | http://localhost:8000 (docs at `/docs`) | [api/README.md](api/README.md) |
| `ui/`        | Streamlit dashboard (the only frontend that currently exists)     | http://localhost:8501                   | [ui/README.md](ui/README.md)   |
| `assistant/` | Gemini function-calling assistant, rendered as the UI's last tab  | n/a — imported by `ui/app.py`           | [assistant/README.md](assistant/README.md) |

## Quick start (Docker)

```bash
docker compose up --build -d      # both services
docker compose logs ui --tail 50  # check for startup errors
docker compose down
```

- API: http://localhost:8000/docs
- UI: http://localhost:8501
- Logs (Dozzle): http://localhost:8888

The Assistant tab needs a `GEMINI_API_KEY` — copy `ui/.env.example` to `ui/.env` and fill it in before building, or the tab will show a notice and the rest of the dashboard works normally. See [assistant/README.md](assistant/README.md) for details.

## Running without Docker

```bash
cd api && pip install -r requirements.txt && uvicorn main:app --reload --port 8000
cd ui  && pip install -r requirements.txt && streamlit run app.py
```

When running the UI directly on the host, set `API_BASE_URL=http://localhost:8000` in `ui/.env` (it's `http://api:8000` under Docker Compose — see [ui/README.md](ui/README.md)).

## Logs

`docker compose up` also starts a [Dozzle](https://dozzle.dev/) container giving a live web view of the `api` and `ui` container logs at http://localhost:8888 — no setup needed, it reads directly from the Docker daemon (mounted read-only) and is filtered to just this project's containers.

Logs are also written to a rotating file per service (`api.log` / `ui.log`, 5 MB x 3 backups), bind-mounted to `./logs/api` and `./logs/ui` on the host via `docker-compose.yml`, so they're available as plain files and survive `docker compose down`/rebuilds, not just restarts.

## Sample data

A sample farm boundary file is at `sample_data/Farm_file.geojson`, useful for trying out upload, validation, and the other tabs.
