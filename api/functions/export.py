from fastapi.responses import JSONResponse
from functions.session import get_dataset


# Get the current GeoJSON data to export
def export_geojson(session_id: str):

    data = get_dataset(session_id)
    return data


def export(session_id: str):

    data = export_geojson(session_id)
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": "attachment; filename=export.geojson"}
    )