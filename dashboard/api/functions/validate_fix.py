import geojson_validator
from functions.session import geojson_dataset
from functions.session import get_dataset

# Invalid criteria with descriptions
CRITERIA_INVALID = {
    "unclosed": "Ring is not closed — first and last coordinate must be identical",
    "less_three_unique_nodes": "Polygon has fewer than 3 unique points",
    "exterior_not_ccw": "Exterior ring is clockwise, must be counterclockwise per RFC 7946",
    "interior_not_cw": "Interior ring (hole) is counterclockwise, must be clockwise per RFC 7946",
    "inner_and_exterior_ring_intersect": "Interior ring crosses the exterior boundary, hole must be fully inside",
}

# Criteria keys as list
CRITERIA_LIST = list(CRITERIA_INVALID.keys())

# Fixed automatically by fix_geometries
AUTO_FIXABLE = {"unclosed", "exterior_not_ccw", "interior_not_cw"}


# Validate the geometry
def validate_geometry():

    data = get_dataset()

    geometry_issues = geojson_validator.validate_geometries(data, CRITERIA_LIST)

    invalid = geometry_issues.get("invalid", {})
    is_valid = not invalid

    return {
        "is_valid": is_valid,
        "summary": {
            "total_features": sum(geometry_issues.get("count_geometry_types", {}).values()),
            "geometry_types": geometry_issues.get("count_geometry_types", {}),
            "invalid_count": sum(len(v) for v in invalid.values()),
        },
        "issues": format_geometry_issues(invalid),
    }


# Fix the geometry issues
def fix_geojson():

    data = get_dataset()

    # Validate before fix
    geometry_issues_before = geojson_validator.validate_geometries(data, CRITERIA_LIST)
    invalid_before = geometry_issues_before.get("invalid", {})

    # Run fix
    fixed = geojson_validator.fix_geometries(data)

    # Overwrite session store
    geojson_dataset["data"] = fixed

    # Validate after fix
    geometry_issues_after = geojson_validator.validate_geometries(fixed, CRITERIA_LIST)
    invalid_after = geometry_issues_after.get("invalid", {})

    # Compare before and after to see what was fixed and what remains
    fixed_invalid = {
        criteria: indices
        for criteria, indices in invalid_before.items()
        if criteria not in invalid_after
    }

    return {
        "message": "Geometries fixed and session updated.",
        "summary": {
            "fixed_count": sum(len(v) for v in fixed_invalid.values()),
            "remaining_count": sum(len(v) for v in invalid_after.values()),
        },
        "fixed":     format_geometry_issues(fixed_invalid),
        "remaining": format_geometry_issues(invalid_after),
    }


# Format geometry issues into readable list
def format_geometry_issues(invalid: dict) -> list:

    formatted = []

    for criteria, feature_indices in invalid.items():
        for feature_index in feature_indices:
            formatted.append({
                "feature":      feature_index,
                "criteria":     criteria,
                "description":  CRITERIA_INVALID.get(criteria, criteria),
                "auto_fixable": criteria in AUTO_FIXABLE
            })

    return formatted