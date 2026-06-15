from fastapi.responses import JSONResponse
from functions.session import get_dataset


# Get the current GeoJSON data to export
def export_geojson():

    data = get_dataset()
    return data


def export():

    data = export_geojson()
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": "attachment; filename=export.geojson"}
    )