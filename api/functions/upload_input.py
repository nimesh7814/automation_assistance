import json
import tempfile
import os
import geojson_validator
from fastapi import HTTPException, UploadFile
from functions.session import set_dataset

VALID_TYPES = ("Polygon", "MultiPolygon")


# File upload
async def upload_geojson(file: UploadFile, session_id: str) -> dict:
    contents = await file.read()
    data, feature_issues = parse_and_validate(contents)
    filtered = filter_geometries(data, feature_issues)
    return process_geojson(data, filtered, session_id)

# Parse the uploaded bytes as JSON and check the GeoJSON structure
def parse_and_validate(contents: bytes) -> tuple[dict, dict]:

    with tempfile.NamedTemporaryFile(mode="w", suffix=".geojson", delete=False) as tmp:
        try:
            tmp.write(contents.decode("utf-8"))
        except UnicodeDecodeError as e:
            os.unlink(tmp.name)
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "File encoding error — must be UTF-8.",
                    "errors": [{"feature": None, "path": None, "type": "encoding", "message": str(e)}]
                }
            )
        tmp_path = tmp.name

    try:
        try:
            with open(tmp_path, "r", encoding="utf-8") as f:
                data = json.load(f)

        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "File is not valid JSON.",
                    "errors": [{
                        "feature": None,
                        "path": None,
                        "type": "json",
                        "message": f"{e.msg} (line {e.lineno}, column {e.colno})"
                    }]
                }
            )

        try:
            issues = geojson_validator.validate_structure(tmp_path)

        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "File is not valid GeoJSON.",
                    "errors": [{"feature": None, "path": None, "type": "structure", "message": str(e)}]
                }
            )

        feature_issues, file_issues = split_structure_issues(issues)

        # Issues not tied to a single feature affect the whole file, so we cannot continue.
        if file_issues:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "GeoJSON structure validation failed.",
                    "errors": file_issues
                }
            )

        return data, feature_issues

    finally:
        os.unlink(tmp_path)

# Split structure issues into ones tied to a specific feature
def split_structure_issues(issues: dict) -> tuple[dict, list]:

    feature_issues = {}
    file_issues = []

    for message, info in issues.items():
        feature_indices = info.get("feature") or []
        paths = info.get("path") or []

        if not feature_indices:
            file_issues.append({
                "feature": None,
                "path": paths[0] if paths else None,
                "type": classify_error(message),
                "message": message
            })
            continue

        for position, feature_index in enumerate(feature_indices):
            path = paths[position] if position < len(paths) else None
            feature_issues.setdefault(feature_index, []).append({
                "path": path,
                "type": classify_error(message),
                "message": message
            })

    return feature_issues, file_issues

# Classify errors into types
def classify_error(message: str) -> str:

    msg = message.lower()

    if "coordinates" in msg:
        return "coordinate"

    if "type" in msg and "must be one of" in msg:
        return "type"

    return "structure"

# Keep only Polygon/MultiPolygon features with no structure issues
def filter_geometries(data: dict, feature_issues: dict) -> dict:

    top_type = data.get("type")
    accepted = []
    rejected = []

    if top_type == "FeatureCollection":

        for index, feature in enumerate(data.get("features", [])):

            # Drop features with structure problems (e.g. missing geometry)
            if index in feature_issues:
                for issue in feature_issues[index]:
                    rejected.append({
                        "feature": index,
                        "geometry_type": None,
                        "properties": feature.get("properties"),
                        **issue
                    })
                continue

            geom_type = (feature.get("geometry") or {}).get("type")

            if geom_type in VALID_TYPES:
                accepted.append(feature)
            else:
                rejected.append({
                    "feature": index,
                    "geometry_type": geom_type,
                    "type": "filter",
                    "message": f"Geometry type '{geom_type}' is not Polygon or MultiPolygon — skipped"
                })

        if not accepted:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "No Polygon or MultiPolygon features found.",
                    "errors": rejected
                }
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
            detail={
                "message": f"'{top_type}' is not accepted.",
                "errors": [{
                    "feature": None,
                    "path": None,
                    "type": "filter",
                    "message": "Must be FeatureCollection, Polygon, or MultiPolygon."
                }]
            }
        )

    return {"accepted": accepted, "rejected": rejected}

# Store the accepted features as the session data and summarise the result
def process_geojson(data: dict, filtered: dict, session_id: str) -> dict:

    accepted = filtered["accepted"]
    rejected = filtered["rejected"]

    processed = {
        "type": "FeatureCollection",
        "features": accepted
    }

    set_dataset(session_id, processed)

    total = len(data.get("features", [])) if data.get("type") == "FeatureCollection" else 1

    return {
        "message": "GeoJSON uploaded successfully.",
        "valid": len(rejected) == 0,
        "errors": rejected,
        "total_features": total,
        "selected_features": len(accepted),
        "processed_geojson": processed
    }
