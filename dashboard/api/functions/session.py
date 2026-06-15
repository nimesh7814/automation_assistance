from fastapi import HTTPException

# Keep the GeoJSON for the duration of the session.
geojson_dataset = {"data": None}


# Return the current GeoJSON data in the session
def get_dataset():

    data = geojson_dataset["data"]
    if data is None:
        raise HTTPException(status_code=404, detail="No GeoJSON data in session. Upload first.")

    return data


# Remove the GeoJSON data from the session
def clear_geojson():

    geojson_dataset["data"] = None

    return {"message": "Session data cleared."}
