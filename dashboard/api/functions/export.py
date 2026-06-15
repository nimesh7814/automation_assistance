from fastapi.responses import JSONResponse
from functions.session import is_data_here


def export_geojson():
    """Export the GeoJSON data."""
    
    data = is_data_here()
    return data


def export():
    
    data = export_geojson()
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": "attachment; filename=export.geojson"}
    )
