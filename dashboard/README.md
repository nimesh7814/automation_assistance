# GeoJSON Dashboard

A small dashboard for working with GeoJSON polygon data: upload a
file, view it on a map and in a table, check for problems (invalid or
duplicate geometries), edit it, and export the result.

It's similar in spirit to [geojson.io](https://geojson.io/), but
tailored to this workflow.

## Parts

| Folder | What it is | Default URL |
| --- | --- | --- |
| [`api/`](api/README.md) | FastAPI backend - validation, editing, undo/redo, export | http://localhost:8000 |
| [`ui-streamlit/`](ui-streamlit/README.md) | Streamlit dashboard | http://localhost:8501 |

The UI talks to the **same API** and the **same in-memory session**.
There is no database and no user accounts - this is a single-session
tool meant for one person exploring one dataset at a time. See
[`api/README.md`](api/README.md) for details.

## Quick start with Docker

From this folder:

```bash
docker compose up --build
```

This starts both services:

- API: http://localhost:8000 (docs at `/docs`)
- Streamlit UI: http://localhost:8501

To run just one service, e.g. `docker compose up --build api`.

## Running without Docker

Each part can also be run directly - see its README for setup steps:

1. [`api/README.md`](api/README.md) - start this first.
2. [`ui-streamlit/README.md`](ui-streamlit/README.md).

## Try it with sample data

A sample farm boundary dataset is included at
[`data/Farm_file.geojson`](data/Farm_file.geojson). Upload it through
the UI to try out the map, table, validation and export features.

## What you can do

- **Upload** a `.geojson` file (only `Polygon`/`MultiPolygon` features
  are kept - others are reported and dropped).
- **View** the data in a table (one row per feature, one column per
  attribute) and on an interactive map.
- **Detect duplicates** - geometries that are identical to another one
  are flagged, with an option to remove them.
- **Detect and fix problem geometries** - invalid or "problematic"
  geometries (self-intersections, unclosed rings, etc.) are listed,
  with an automatic fix option.
- **Edit** the data: draw new polygons, edit existing geometries,
  delete features, and edit attribute values.
- **Undo/redo** changes and **export** the result as `.geojson`.
- **Error logging** - the API logs requests and unexpected errors to
  the console, and always returns a friendly error message to the UI.
