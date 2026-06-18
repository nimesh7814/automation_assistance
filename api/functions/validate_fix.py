import geojson_validator
from shapely.geometry import Polygon, shape
from shapely.errors import TopologicalError
from functions.session import get_dataset, set_dataset


# Criteria
CRITERIA_INVALID = {
    # geojson_validator supported
    "unclosed": "Ring is not closed",
    "less_three_unique_nodes": "Polygon has fewer than 3 unique points",
    "exterior_not_ccw": "Exterior ring is clockwise, must be counterclockwise per RFC 7946",
    "interior_not_cw": "Interior ring (hole) is counterclockwise, must be clockwise per RFC 7946",
    "inner_and_exterior_ring_intersect": "Interior ring crosses the exterior boundary, hole must be fully inside",
    # Custom checks
    "empty_geometry": "Geometry is null or has no coordinates",
    "self_intersection": "Polygon edges cross themselves, creating an invalid shape",
    "hole_outside": "Interior ring (hole) lies outside the exterior boundary",
}

VALIDATOR_CRITERIA = [
    "unclosed",
    "less_three_unique_nodes",
    "exterior_not_ccw",
    "interior_not_cw",
    "inner_and_exterior_ring_intersect",
]

# Only empty_geometry is safe to auto-fix
AUTO_FIXABLE = {"unclosed", "exterior_not_ccw", "interior_not_cw", "empty_geometry"}


# Custom geometry checks
def check_empty_geometry(features: list) -> list:
    indices = []
    for idx, feature in enumerate(features):
        geom = feature.get("geometry")
        if geom is None:
            indices.append(idx)
            continue
        coords = geom.get("coordinates")
        if coords is None or coords == [] or coords == [[]]:
            indices.append(idx)
    return indices


def check_self_intersection(features: list) -> list:
    indices = []

    def has_enough_unique_points(ring) -> bool:
        return len({tuple(coord[:2]) for coord in ring.coords}) >= 3

    for idx, feature in enumerate(features):
        geom = feature.get("geometry")
        if not geom:
            continue
        try:
            shapely_geom = shape(geom)
            polys = (
                list(shapely_geom.geoms)
                if shapely_geom.geom_type == "MultiPolygon"
                else [shapely_geom]
            )
            for poly in polys:
                if has_enough_unique_points(poly.exterior) and not poly.exterior.is_simple:
                    indices.append(idx)
                    break
                if any(
                    has_enough_unique_points(interior) and not interior.is_simple
                    for interior in poly.interiors
                ):
                    indices.append(idx)
                    break
        except (ValueError, AttributeError, TypeError, TopologicalError):
            pass
    return indices


def check_hole_outside(features: list) -> list:
    indices = []
    for idx, feature in enumerate(features):
        geom = feature.get("geometry")
        if not geom:
            continue
        try:
            shapely_geom = shape(geom)
            polys = (
                list(shapely_geom.geoms)
                if shapely_geom.geom_type == "MultiPolygon"
                else [shapely_geom]
            )
            for poly in polys:
                shell = Polygon(poly.exterior)
                for interior in poly.interiors:
                    hole = Polygon(interior)
                    if not shell.contains(hole):
                        indices.append(idx)
                        break
                else:
                    continue
                break
        except (ValueError, AttributeError, TypeError, TopologicalError):
            pass
    return indices


def run_custom_checks(features: list) -> dict:
    results = {}

    empty = check_empty_geometry(features)
    self_ix = check_self_intersection(features)
    hole = check_hole_outside(features)

    if empty:
        results["empty_geometry"] = empty
    if self_ix:
        results["self_intersection"] = self_ix
    if hole:
        results["hole_outside"] = hole

    return results


# geojson_validator's own checks (e.g. check_unclosed) index straight into
# coordinates[0] and raise an unhandled IndexError on a feature with no
# coordinates at all - swap those features for a trivially valid placeholder
# just for this call so the library never sees an empty geometry. The real
# empty_geometry check (above) runs separately against the unmodified data,
# so the feature is still correctly reported/dropped - this only stops the
# library call itself from crashing the request before that can happen.
_EMPTY_GEOMETRY_PLACEHOLDER = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}


def safe_validate_geometries(data: dict, criteria: list) -> dict:
    features = data.get("features", [])
    empty_indices = set(check_empty_geometry(features))
    if not empty_indices:
        return geojson_validator.validate_geometries(data, criteria)

    safe_features = [
        {**feature, "geometry": _EMPTY_GEOMETRY_PLACEHOLDER} if idx in empty_indices else feature
        for idx, feature in enumerate(features)
    ]
    return geojson_validator.validate_geometries({**data, "features": safe_features}, criteria)


# Formatting
def format_geometry_issues(invalid: dict) -> list:
    formatted = []
    for criteria, feature_indices in invalid.items():
        for feature_index in feature_indices:
            formatted.append({
                "feature": feature_index,
                "criteria": criteria,
                "description": CRITERIA_INVALID.get(criteria, criteria),
                "auto_fixable": criteria in AUTO_FIXABLE,
            })
    return formatted


# Validate
def validate_geometry(session_id: str):
    data = get_dataset(session_id)
    features = data.get("features", [])

    # geojson_validator checks
    geometry_issues = safe_validate_geometries(data, VALIDATOR_CRITERIA)
    invalid = geometry_issues.get("invalid", {})

    # Custom checks
    custom_invalid  = run_custom_checks(features)
    invalid = {**invalid, **custom_invalid}

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


# Fix

def fix_geojson(session_id: str):
    data = get_dataset(session_id)
    features = data.get("features", [])

    # Validate before fix
    geometry_issues_before = safe_validate_geometries(data, VALIDATOR_CRITERIA)
    invalid_before = {
        **geometry_issues_before.get("invalid", {}),
        **run_custom_checks(features),
    }

    # Fix empty geometries (drop them)
    empty_indices = set(invalid_before.get("empty_geometry", []))
    if empty_indices:
        data["features"] = [
            f for idx, f in enumerate(features) if idx not in empty_indices
        ]

    # Fix unclosed / winding issues via geojson_validator
    fixed = geojson_validator.fix_geometries(data)

    # Overwrite session
    set_dataset(session_id, fixed)

    # Validate after fix
    features_after = fixed.get("features", [])
    geometry_issues_after  = safe_validate_geometries(fixed, VALIDATOR_CRITERIA)
    invalid_after = {
        **geometry_issues_after.get("invalid", {}),
        **run_custom_checks(features_after),
    }

    # What was resolved
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
        "fixed": format_geometry_issues(fixed_invalid),
        "remaining": format_geometry_issues(invalid_after),
    }
