from fastapi import HTTPException
from functions.session import is_data_here


def update_geometry_geojson(feature_id: int, new_geometry: dict):
    
    data = is_data_here()
    features = data["features"]

    # Check the feature_id is within range
    if feature_id < 0 or feature_id >= len(features):
        raise HTTPException(status_code=404, detail=f"Feature {feature_id} not found. Valid range is 0 to {len(features) - 1}.")

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

    
def add_feature_geojson(new_feature: dict):
    """Add a new feature to the GeoJSON data."""
    
    data = is_data_here()

    # Check the new feature has a geometry
    if not new_feature.get("geometry"):
        raise HTTPException(status_code=400, detail="Feature must include a geometry.")

    # Check the geometry is a Polygon or MultiPolygon
    if new_feature["geometry"].get("type") not in ("Polygon", "MultiPolygon"):
        raise HTTPException(status_code=400, detail="Geometry must be a Polygon or MultiPolygon.")

    # Add the new feature to the session store
    data["features"].append(new_feature)

    return {
        "message": "Feature added successfully.",
        "new_feature_id": len(data["features"]) - 1,
        "total_features": len(data["features"])
    }


def update_properties_geojson(feature_id: int, new_properties: dict):
    """Update the properties of a feature."""
    
    data = is_data_here()
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
