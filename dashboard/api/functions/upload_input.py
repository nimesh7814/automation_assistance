import json
import geojson
from fastapi import HTTPException, UploadFile
from functions.session import geojson_dataset

VALID_TYPES = ("Polygon", "MultiPolygon")

# Process file GeoJSON input
async def upload_geojson(file: UploadFile) -> dict:
    contents = await file.read()
    data = parse_geojson(contents)
    filtered = filter_geometries(data)
    return process_geojson(data, filtered)


# Process text GeoJSON input
def text_geojson(raw: str | dict) -> dict:
    if isinstance(raw, dict):
        raw = json.dumps(raw)

    data = parse_geojson(raw.encode("utf-8"))
    filtered = filter_geometries(data)
    return process_geojson(data, filtered)


# Parser
def parse_geojson(contents: bytes) -> dict:
    try:
        return geojson.loads(contents.decode("utf-8"))
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid GeoJSON: {str(e)}"
        )


# Filter Polygon and MultiPolygon geometries
def filter_geometries(data: dict) -> dict:
    top_type = data.get("type")
    accepted = []
    rejected = []

    if top_type == "FeatureCollection":
        for index, feature in enumerate(data.get("features", [])):
            geom_type = feature.get("geometry", {}).get("type")

            if geom_type in VALID_TYPES:
                accepted.append(feature)
            else:
                rejected.append({
                    "index": index,
                    "geometry_type": geom_type,
                    "reason": f"Geometry type '{geom_type}' is not Polygon or MultiPolygon"
                })

        if not accepted:
            raise HTTPException(
                status_code=400,
                detail="No Polygon or MultiPolygon features found in the FeatureCollection."
            )

    elif top_type in VALID_TYPES:
        accepted.append({
            "type": "Feature",
            "geometry": data,
            "properties": {}
        })

    else:
        raise HTTPException(
            status_code=400,
            detail=f"'{top_type}' is not accepted. Must be FeatureCollection, Polygon, or MultiPolygon."
        )

    return {"accepted": accepted, "rejected": rejected}


# Process output
def process_geojson(data: dict, filtered: dict) -> dict:
    accepted = filtered["accepted"]
    rejected = filtered["rejected"]

    processed = {
        "type": "FeatureCollection",
        "features": accepted
    }

    geojson_dataset["data"] = processed

    if data.get("type") == "FeatureCollection":
        total = len(data.get("features", []))
    else:
        total = 1

    return {
        "message": "GeoJSON uploaded successfully.",
        "errors": rejected,
        "total_features": total,
        "selected_features": len(accepted),
        "processed_geojson": processed
    }