from fastapi import HTTPException

# Keep the GeoJSON for the duration of the session.
geojson_dataset = {"data": None}


def is_data_here():

    data = geojson_dataset["data"]
    if data is None:
        raise HTTPException(status_code=404, detail="No GeoJSON data in session. Upload first.")

    return data


def clear_geojson():
    """Clear the GeoJSON data from the session."""
    
    geojson_dataset["data"] = None

    return {"message": "Session data cleared."}
