# GeoJSON Dashboard API

A small FastAPI backend that powers the Streamlit dashboard
(`ui-streamlit`). It accepts a GeoJSON file, keeps it in memory for the
current session, and exposes endpoints to inspect, validate, edit and
export it.

## How it works

The uploaded GeoJSON is kept in a single in-memory variable
(`geojson_dataset` in `geojason.py`). There is **no database and no
user accounts** - it's one shared session for whoever is using the API
at the time. This keeps the project simple and is fine for a single
user trying out the dashboard, but:

- Restarting the API loses the data.
- Two people using the dashboard at the same time will see and edit
  the same dataset.

Only `Polygon` and `MultiPolygon` features are kept. Anything else
(points, lines, etc.) is dropped on upload and reported in the upload
summary.

## Running locally

```bash
cd dashboard/api
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

The API is then available at `http://localhost:8000`. Interactive docs
(Swagger UI) are at `http://localhost:8000/docs`.

## Running with Docker

From the `dashboard` folder:

```bash
docker compose up --build api
```

or start the whole stack (API + Streamlit UI) with `docker compose up --build`.

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/upload/file` | Upload a `.geojson` file (multipart form, field name `file`). |
| `GET` | `/features` | Return all features currently in the session. |
| `GET` | `/validate` | Check the geometries for structural and topology issues. |
| `POST` | `/fix` | Try to automatically repair invalid/problematic geometries. |
| `GET` | `/duplicates?remove_duplicates=false` | Find geometries that are identical to another one. Pass `true` to delete the duplicates. |
| `POST` | `/features` | Add a new feature (geometry + properties). |
| `PUT` | `/features/{id}/geometry` | Replace the geometry of a feature. |
| `PUT` | `/features/{id}/properties` | Replace the attribute table (properties) of a feature. |
| `DELETE` | `/features/{id}` | Delete a feature. |
| `GET` | `/export` | Download the current dataset as a `.geojson` file. |
| `DELETE` | `/data` | Clear the session and start over. |

All endpoints return JSON. Errors come back in the same shape:
`{"message": "...", "errors": [...]}` with an appropriate HTTP status
code (e.g. `400` for bad input, `404` if nothing has been uploaded
yet). `errors` is a list of details (e.g. which feature had a problem)
and is empty when there is nothing extra to report.

## Geometry validation

Validation and auto-fix are powered by the
[`geojson_validator`](https://github.com/chrieke/geojson-validator)
package. `/validate` reports:

- **Structure issues** - problems with the overall GeoJSON (e.g. CRS).
- **Geometry issues** - split into `invalid` (e.g. unclosed rings, too
  few points) and `problematic` (e.g. self-intersections, holes,
  duplicate vertices, coordinates outside lat/lon range).

`/fix` attempts to repair the `invalid`/`problematic` geometries and
reports what was fixed and what is still left afterwards.

## Logging

Requests and unexpected errors are logged to the console (visible with
`docker compose logs api`). Any error that isn't already a handled
`HTTPException` is logged with a full traceback and returns a generic
`500` message to the client, so internal details are never leaked to
the UI.

## Sample data

A sample farm boundary file is provided at
`dashboard/data/Farm_file.geojson` - useful for trying out the upload
and the other endpoints.
