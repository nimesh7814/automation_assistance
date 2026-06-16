from fastapi import HTTPException
from functions.session import get_dataset


# Replace the geometry of an existing feature
def update_geometry_geojson(session_id: str, feature_id: int, new_geometry: dict):

    data = get_dataset(session_id)
    features = data["features"]

    # Check the feature_id is within range
    if feature_id < 0 or feature_id >= len(features):
        raise HTTPException(status_code=404, detail=f"Feature {feature_id} not found. Valid range is 0 to {len(features) - 1}.")

    # Check a geometry was sent at all
    if not isinstance(new_geometry, dict):
        raise HTTPException(status_code=400, detail="Request body must include a 'geometry' object.")

    # Check the new geometry has a valid type
    if new_geometry.get("type") not in ("Polygon", "MultiPolygon"):
        raise HTTPException(status_code=400, detail="Geometry must be a Polygon or MultiPolygon.")

    # Check the new geometry has coordinates
    if not new_geometry.get("coordinates"):
        raise HTTPException(status_code=400, detail="Geometry must include coordinates.")

    # Save the new geometry
    features[feature_id]["geometry"] = new_geometry

    # Return the updated feature
    return {
        "message": f"Geometry of feature {feature_id} updated successfully.",
        "feature_id": feature_id,
        "updated_feature": features[feature_id]
    }


# Add a brand new feature (e.g. a polygon drawn on the map)
def add_feature_geojson(session_id: str, new_feature: dict):

    data = get_dataset(session_id)

    # Check the new feature has a geometry
    geometry = new_feature.get("geometry")
    if not isinstance(geometry, dict):
        raise HTTPException(status_code=400, detail="Feature must include a geometry.")

    # Check the geometry is a Polygon or MultiPolygon
    if geometry.get("type") not in ("Polygon", "MultiPolygon"):
        raise HTTPException(status_code=400, detail="Geometry must be a Polygon or MultiPolygon.")

    # Fill in the standard GeoJSON feature fields if they are missing
    new_feature.setdefault("type", "Feature")
    new_feature.setdefault("properties", {})

    # Add the new feature to the session store
    data["features"].append(new_feature)

    return {
        "message": "Feature added successfully.",
        "new_feature_id": len(data["features"]) - 1,
        "total_features": len(data["features"])
    }


# Replace the attribute table (properties) of a feature
def update_properties_geojson(session_id: str, feature_id: int, new_properties: dict):

    data = get_dataset(session_id)
    features = data["features"]

    # Check the feature_id is within range
    if feature_id < 0 or feature_id >= len(features):
        raise HTTPException(status_code=404, detail=f"Feature {feature_id} not found. Valid range is 0 to {len(features) - 1}.")

    # Replace the properties
    features[feature_id]["properties"] = new_properties

    return {
        "message": f"Properties of feature {feature_id} updated successfully.",
        "feature_id": feature_id,
        "updated_properties": new_properties
    }
