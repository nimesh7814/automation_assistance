import geojson_validator
from fastapi import HTTPException
from functions.session import geojson_dataset
from functions.session import is_data_here

# Invalid criteria
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


def validate_geojson():
    """Validate the GeoJSON data structure and geometries."""
    
    data = is_data_here()

    structure_issues = geojson_validator.validate_structure(data, check_crs=True)
    geometry_issues = geojson_validator.validate_geometries(data, CRITERIA_INVALID, CRITERIA_PROBLEMATIC)

    is_valid = not structure_issues and not geometry_issues.get("invalid")

    return {
        "is_valid": is_valid,
        "structure_issues": structure_issues,
        "geometry_issues": geometry_issues,
    }

    
def fix_geojson():
    """Fix geometry issues in the GeoJSON data."""
    
    data = is_data_here()

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
