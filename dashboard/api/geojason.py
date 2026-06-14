from fastapi import HTTPException
import geojson_validator

# Keep the GeoJSON for the duration of the session.
geojson_dataset = {"data": None}

# Invalid crieteria
CRITERIA_INVALID = [
    "unclosed",
    "less_three_unique_nodes",
    "exterior_not_ccw",
    "interior_not_cw",
    "inner_and_exterior_ring_intersect",
]

# Problematic geometries 
CRITERIA_PROBLEMATIC = [
    "holes",
    "self_intersection",
    "duplicate_nodes",
    "excessive_coordinate_precision",
    "excessive_vertices",
    "3d_coordinates",
    "outside_lat_lon_boundaries",
    # "crosses_antimeridian",
]

# Function to process GeoJSON
def process_geojson(data: dict):

    # Validate that the GeoJSON is a FeatureCollection
    if data.get("type") != "FeatureCollection":
        raise HTTPException(status_code=400, detail="GeoJSON must be a FeatureCollection.")

    if not isinstance(data.get("features"), list):
        raise HTTPException(status_code=400, detail="GeoJSON must include a features list.")

    # Filter out non-polygon features and keep only polygons
    polygons = [
        feature for feature in data["features"]
        if feature.get("geometry", {}).get("type") in ("Polygon", "MultiPolygon")
    ]

    # Save to the session store
    geojson_dataset["data"] = {"type": "FeatureCollection", "features": polygons}

    # Return the summary
    return {
        "message": "GeoJSON processed successfully.",
        "total_features": len(data["features"]),
        "polygons_kept": len(polygons),
        "non_polygons_removed": len(data["features"]) - len(polygons)
    }


# Validate the GeoJSON
def validate_geojson():

    data = geojson_dataset["data"]
    if data is None:
        raise HTTPException(status_code=404, detail="No GeoJSON data in session. Upload first.")

    structure_issues = geojson_validator.validate_structure(data, check_crs=True)
    geometry_issues = geojson_validator.validate_geometries(data, CRITERIA_INVALID, CRITERIA_PROBLEMATIC)

    is_valid = not structure_issues and not geometry_issues.get("invalid")

    return {
        "is_valid": is_valid,
        "structure_issues": structure_issues,
        "geometry_issues": geometry_issues,
    }
    
# Fix the GeoJSON
def fix_geojson():

    data = geojson_dataset["data"]
    if data is None:
        raise HTTPException(status_code=404, detail="No GeoJSON data in session. Upload first.")

    # Validate
    geometry_issues_before = geojson_validator.validate_geometries(data, CRITERIA_INVALID, CRITERIA_PROBLEMATIC)
    invalid_before = geometry_issues_before.get("invalid", {})
    problematic_before = geometry_issues_before.get("problematic", {})

    # Run fix
    fixed = geojson_validator.fix_geometries(data)

    # Overwrite session store
    geojson_dataset["data"] = fixed

    # Validate after fix
    geometry_issues_after = geojson_validator.validate_geometries(
        fixed, CRITERIA_INVALID, CRITERIA_PROBLEMATIC
    )
    invalid_after = geometry_issues_after.get("invalid", {})
    problematic_after = geometry_issues_after.get("problematic", {})

    # Summarise what was fixed vs what remains
    fixed_invalid = {k: len(v) for k, v in invalid_before.items() if k not in invalid_after}
    fixed_problematic = {k: len(v) for k, v in problematic_before.items() if k not in problematic_after}

    still_invalid = {k: len(v) for k, v in invalid_after.items()}
    still_problematic = {k: len(v) for k, v in problematic_after.items()}

    return {
        "message": "Geometries fixed and session updated.",
        "fixed": {
            "invalid": fixed_invalid,
            "problematic": fixed_problematic,
        },
        "remaining": {
            "invalid": still_invalid,
            "problematic": still_problematic,
        },
    }