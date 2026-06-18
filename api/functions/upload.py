import json
import geojson_validator
from fastapi import HTTPException, UploadFile
from functions.session import set_crs_status, set_dataset

VALID_TYPES = ("Polygon", "MultiPolygon")
ACCEPTED_CRS = "urn:ogc:def:crs:OGC:1.3:CRS84"


async def upload_geojson(file: UploadFile, session_id: str) -> dict:
    contents = await file.read()

    try:
        data = json.loads(contents.decode("utf-8"))
    except UnicodeDecodeError as e:
        raise_error(400, "File encoding error — must be UTF-8.", [err(type="encoding", message=str(e))])
    except json.JSONDecodeError as e:
        raise_error(400, "File is not valid JSON.", [err(type="json", message=f"{e.msg} (line {e.lineno}, column {e.colno})")])

    feature_issues, file_issues = parse_structure_issues(data)

    if file_issues:
        raise_error(400, "GeoJSON structure validation failed.", file_issues)

    accepted, rejected = filter_geometries(data, feature_issues)

    if not accepted:
        raise_error(400, "No Polygon or MultiPolygon features found.", rejected)

    return process_geojson(data, accepted, rejected, session_id)


def parse_structure_issues(data: dict) -> tuple[dict, list]:
    """Validate GeoJSON structure and split issues into feature-level vs file-level."""
    try:
        raw_issues = geojson_validator.validate_structure(data)
    except ValueError as e:
        raise_error(400, "File is not valid GeoJSON.", [err(type="structure", message=str(e))])

    feature_issues, file_issues = {}, []

    for message, info in raw_issues.items():
        issue_type = "coordinate" if "coordinates" in message.lower() else "type" if "type" in message.lower() and "must be one of" in message.lower() else "structure"
        indices = info.get("feature") or []
        paths = info.get("path") or []

        if not indices:
            file_issues.append(err(path=paths[0] if paths else None, type=issue_type, message=message))
        else:
            for pos, idx in enumerate(indices):
                feature_issues.setdefault(idx, []).append(err(path=paths[pos] if pos < len(paths) else None, type=issue_type, message=message))

    return feature_issues, file_issues


def filter_geometries(data: dict, feature_issues: dict) -> tuple[list, list]:
    """Return (accepted_features, rejected_entries) based on geometry type and structure."""
    top_type = data.get("type")

    if top_type not in ("FeatureCollection", *VALID_TYPES):
        raise_error(400, f"'{top_type}' is not accepted.", [err(type="filter", message="Must be FeatureCollection, Polygon, or MultiPolygon.")])

    if top_type in VALID_TYPES:
        return [{"type": "Feature", "geometry": data, "properties": {}}], []

    accepted, rejected = [], []

    for index, feature in enumerate(data.get("features", [])):
        if index in feature_issues:
            rejected += [{"feature": index, "geometry_type": None, "properties": feature.get("properties"), **issue} for issue in feature_issues[index]]
            continue

        geom_type = (feature.get("geometry") or {}).get("type")
        if geom_type in VALID_TYPES:
            accepted.append(feature)
        else:
            rejected.append(err(feature=index, geometry_type=geom_type, type="filter", message=f"Geometry type '{geom_type}' is not Polygon or MultiPolygon — skipped"))

    return accepted, rejected


def process_geojson(data: dict, accepted: list, rejected: list, session_id: str) -> dict:
    # RFC 7946-compliant files omit `crs` entirely (always WGS84/CRS84) - only
    # flag it when present and pointing at something other than CRS84, since
    # the app has no reprojection step and would otherwise mis-place geometry.
    crs_value = data.get("crs")
    crs_name = crs_value.get("properties", {}).get("name") if isinstance(crs_value, dict) else None
    crs_ok = crs_value is None or crs_name == ACCEPTED_CRS

    processed = {"type": "FeatureCollection", "features": accepted}
    set_dataset(session_id, processed)

    errors = rejected[:]
    if not crs_ok:
        errors.append(err(type="crs", message=f"Unsupported CRS '{crs_name or crs_value}' — expected {ACCEPTED_CRS} or no CRS."))

    crs_status = {
        "present": crs_value is not None,
        "name": crs_name,
        "accepted": crs_ok,
        "value": crs_value
    }
    set_crs_status(session_id, crs_status)

    return {
        "message": "GeoJSON uploaded successfully.",
        "valid": not errors,
        "errors": errors,
        "total_features": len(data.get("features", [])) if data.get("type") == "FeatureCollection" else 1,
        "selected_features": len(accepted),
        "crs": crs_status,
        "processed_geojson": processed,
    }


# Helpers
def err(**kwargs) -> dict:
    return {"feature": None, "path": None, **kwargs}

def raise_error(status: int, message: str, errors: list):
    raise HTTPException(status_code=status, detail={"message": message, "errors": errors})
