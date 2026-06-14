from fastapi import HTTPException
import geojson_validator
import json

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


def is_data_here():
    data = geojson_dataset["data"]
    if data is None:
        raise HTTPException(status_code=404, detail="No GeoJSON data in session. Upload first.")

    return data


# Function to process GeoJSON
def process_geojson(data: dict):

    # Validate that the GeoJSON is a FeatureCollection
    if data.get("type") != "FeatureCollection":
        raise HTTPException(status_code=400, detail="GeoJSON must be a FeatureCollection.")

    if not isinstance(data.get("features"), list):
        raise HTTPException(status_code=400, detail="GeoJSON must include a features list.")

    # Check CRS — GeoJSON standard (RFC 7946) assumes WGS84 (EPSG:4326)
    crs = data.get("crs")
    raw_crs = crs.get("properties", {}).get("name") if crs else ""

    # Normalise CRS84 and EPSG:4326 to a clean label
    if not raw_crs:
        crs_label = "EPSG:4326"
        crs_warning = None
    elif "4326" in raw_crs or "CRS84" in raw_crs:
        crs_label = "EPSG:4326 / WGS84 (valid)"
        crs_warning = None
    else:
        crs_label = raw_crs
        crs_warning = f"Non-standard CRS detected: '{raw_crs}'."

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
        "crs": crs_label,
        "crs_warning": crs_warning,
        "total_features": len(data["features"]),
        "polygons_kept": len(polygons),
        "non_polygons_removed": len(data["features"]) - len(polygons)
    }

# Validate the GeoJSON
def validate_geojson():

    data = is_data_here()

    structure_issues = geojson_validator.validate_structure(data, check_crs=True)
    geometry_issues = geojson_validator.validate_geometries(data, CRITERIA_INVALID, CRITERIA_PROBLEMATIC)

    is_valid = not structure_issues and not geometry_issues.get("invalid")

    return {
        "is_valid": is_valid,
        "structure_issues": structure_issues,
        "geometry_issues": geometry_issues,
    }
    
# Fix the GeoJSON
def fix_geojson(undo_history: list):

    data = is_data_here()

    # Save snapshot before fixing so it can be undone
    undo_history.append({
        "action": "fix_geometries",
        "snapshot": json.dumps(data)
    })

    # Validate before fix
    geometry_issues_before = geojson_validator.validate_geometries(data, CRITERIA_INVALID, CRITERIA_PROBLEMATIC)
    invalid_before = geometry_issues_before.get("invalid", {})
    problematic_before = geometry_issues_before.get("problematic", {})

    # Run fix
    fixed = geojson_validator.fix_geometries(data)

    # Overwrite session store
    geojson_dataset["data"] = fixed

    # Validate after fix
    geometry_issues_after = geojson_validator.validate_geometries(fixed, CRITERIA_INVALID, CRITERIA_PROBLEMATIC)
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

# Find Duplicate Geometries
def detect_duplicates(remove_duplicates: bool = False):

    data = is_data_here()
    features = data["features"]

    # Convert each feature geometry to a string to allow comparison
    geometry_strings = [
        json.dumps(feature.get("geometry"), sort_keys=True)
        for feature in features
    ]

    # Group feature indices by their geometry string
    seen = {}
    for index, geometry_str in enumerate(geometry_strings):
        if geometry_str not in seen:
            seen[geometry_str] = []
        seen[geometry_str].append(index)

    # Assign a group number to each duplicate group
    # position 0 = kept copy, position 1+ = duplicates to remove
    duplicate_group_map = {}
    group_number = 1
    for indices in seen.values():
        if len(indices) > 1:
            for position, index in enumerate(indices):
                duplicate_group_map[index] = {
                    "group": group_number,
                    "is_duplicate": 0 if position == 0 else 1
                }
            group_number += 1

    # Indices to remove — only the copies, not the first occurrence
    indices_to_remove = [
        index for index, info in duplicate_group_map.items()
        if info["is_duplicate"] == 1
    ]

    # Build the feature list with flags
    features_with_flag = []
    for index, feature in enumerate(features):
        group_info = duplicate_group_map.get(index)
        features_with_flag.append({
            "feature_id": index,
            "is_duplicate": group_info["is_duplicate"] if group_info else 0,
            "duplicate_group": group_info["group"] if group_info else None,
            "properties": feature.get("properties"),
            "geometry_type": feature.get("geometry", {}).get("type")
        })

    # Only remove if explicitly requested
    if remove_duplicates and indices_to_remove:

        # Remove in reverse order so indices don't shift
        for index in sorted(indices_to_remove, reverse=True):
            data["features"].pop(index)

        # Rebuild the flag list — only kept features, clean duplicate_group to null
        features_with_flag = []
        for new_id, feature in enumerate(data["features"]):
            features_with_flag.append({
                "feature_id": new_id,
                "is_duplicate": 0,
                "duplicate_group": None,   # ← now null since duplicates are gone
                "properties": feature.get("properties"),
                "geometry_type": feature.get("geometry", {}).get("type")
            })

    return {
        "total_features_before": len(features) + len(indices_to_remove) if remove_duplicates else len(features),
        "duplicate_groups_found": group_number - 1,
        "removed": len(indices_to_remove) if remove_duplicates else 0,
        "total_features_after": len(data["features"]),
        "features": features_with_flag
    }
    
# Edit Geometry of a Given Feature
def update_geometry_geojson(feature_id: int, new_geometry: dict, undo_history: list):

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

    # Save old geometry to undo history before making the change
    undo_history.append({
        "action": "update_geometry",
        "feature_id": feature_id,
        "old_geometry": features[feature_id]["geometry"]
    })

    # Save the new geometry
    features[feature_id]["geometry"] = new_geometry

    # Return the updated feature
    return {
        "message": f"Geometry of feature {feature_id} updated successfully.",
        "feature_id": feature_id,
        "updated_feature": features[feature_id]
    }
    
# Add a new feature
def add_feature_geojson(new_feature: dict, undo_history: list):

    data = is_data_here()

    # Check the new feature has a geometry
    if not new_feature.get("geometry"):
        raise HTTPException(status_code=400, detail="Feature must include a geometry.")

    # Check the geometry is a Polygon or MultiPolygon
    if new_feature["geometry"].get("type") not in ("Polygon", "MultiPolygon"):
        raise HTTPException(status_code=400, detail="Geometry must be a Polygon or MultiPolygon.")

    # Save current state to undo history before making changes
    undo_history.append({
        "action": "add_feature",
        "snapshot": json.dumps(data)
    })

    # Add the new feature to the session store
    data["features"].append(new_feature)

    return {
        "message": "Feature added successfully.",
        "new_feature_id": len(data["features"]) - 1,
        "total_features": len(data["features"])
    }


# Delete a feature
def delete_feature_geojson(feature_id: int, undo_history: list):

    data = is_data_here()
    features = data["features"]

    # Check the feature_id is within range
    if feature_id < 0 or feature_id >= len(features):
        raise HTTPException(status_code=404, detail=f"Feature {feature_id} not found. Valid range is 0 to {len(features) - 1}.")

    # Save current state to undo history before making changes
    undo_history.append({
        "action": "delete_feature",
        "feature_id": feature_id,
        "snapshot": json.dumps(data)
    })

    # Remove the feature
    removed = features.pop(feature_id)

    return {
        "message": f"Feature {feature_id} deleted successfully.",
        "deleted_feature": removed,
        "total_features": len(features)
    }


# Update properties of a feature
def update_properties_geojson(feature_id: int, new_properties: dict, undo_history: list):

    data = is_data_here()
    features = data["features"]

    # Check the feature_id is within range
    if feature_id < 0 or feature_id >= len(features):
        raise HTTPException(status_code=404, detail=f"Feature {feature_id} not found. Valid range is 0 to {len(features) - 1}.")

    # Save current state to undo history before making changes
    undo_history.append({
        "action": "update_properties",
        "feature_id": feature_id,
        "old_properties": features[feature_id]["properties"]
    })

    # Replace the properties
    features[feature_id]["properties"] = new_properties

    return {
        "message": f"Properties of feature {feature_id} updated successfully.",
        "feature_id": feature_id,
        "updated_properties": new_properties
    }


# Undo the last change
def undo_geojson(undo_history: list):

    # Check there is something to undo
    if not undo_history:
        raise HTTPException(status_code=400, detail="Nothing to undo.")

    # Get the last action
    last_action = undo_history.pop()

    # Restore the snapshot if available
    if "snapshot" in last_action:
        geojson_dataset["data"] = json.loads(last_action["snapshot"])

    # Restore old properties if available
    elif last_action["action"] == "update_properties":
        feature_id = last_action["feature_id"]
        geojson_dataset["data"]["features"][feature_id]["properties"] = last_action["old_properties"]

    # Restore old geometry if available
    elif last_action["action"] == "update_geometry":
        feature_id = last_action["feature_id"]
        geojson_dataset["data"]["features"][feature_id]["geometry"] = last_action["old_geometry"]

    return {
        "message": f"Undid action: {last_action['action']}",
        "remaining_undo_steps": len(undo_history)
    }


# Export the GeoJSON
def export_geojson():

    data = is_data_here()

    return data