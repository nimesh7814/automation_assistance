import geojson
import geojson_validator
from json import JSONDecodeError
from fastapi import HTTPException, UploadFile

from functions.logging import logger
from functions.session import set_crs_status, set_dataset

ALLOWED_GEOMETRIES = ["Polygon", "MultiPolygon"]
ALLOWED_ROOT_TYPES = ["FeatureCollection", *ALLOWED_GEOMETRIES]
ALLOWED_CRS = ["urn:ogc:def:crs:OGC:1.3:CRS84", "EPSG:4326" ,"urn:ogc:def:crs:EPSG::4326"]

# Upload function for FastAPI endpoint
async def upload_geojson(file: UploadFile, session_id: str) -> dict:

    file_contents = await file.read()
    geojson_data = load_geojson_from_bytes(file_contents)
    geojson_data = normalize_root_type(geojson_data)
    structure_errors = validate_geojson_structure(geojson_data)
    feature_issues = parse_feature_level_issues(structure_errors)
    accepted_features, rejected_features = filter_geometry_types(
        geojson_data,
        feature_issues,
        ALLOWED_GEOMETRIES
    )

    if not accepted_features:
        raise_api_error(
            status_code=400,
            message="No Polygon or MultiPolygon features found.",
            errors=rejected_features
        )

    return build_upload_response(
        geojson_data=geojson_data,
        accepted_features=accepted_features,
        rejected_features=rejected_features,
        session_id=session_id
    )

# Load GeoJSON and Parse Errors
def load_geojson_from_bytes(file_contents: bytes) -> dict:

    try:
        decoded_text = file_contents.decode("utf-8")
        return geojson.loads(decoded_text)

    except UnicodeDecodeError as error:
        raise_api_error(
            status_code=400,
            message="Unicode Error: File must be UTF-8 encoded.",
            errors=[create_error(error_type="encoding",message=str(error))]
        )

    except JSONDecodeError as error:
        raise_api_error(
            status_code=400,
            message="JSON Error: File is not valid JSON.",
            errors=[create_error(error_type="json", message=f"{error.msg} (line {error.lineno}, column {error.colno})")]
        )

    except Exception as error:
        # geojson.loads() does its own eager validation (e.g. a missing
        # 'features' array, non-numeric coordinates) and raises whatever
        # internal exception that produces - log the real one, but don't
        # forward Python-internal text (constructor signatures, etc.) to the client.
        logger.warning(f"Unexpected error parsing uploaded GeoJSON: {error}")
        raise_api_error(
            status_code=400,
            message="File is not a well-formed GeoJSON document.",
            errors=[create_error(
                error_type="structure",
                message="Could not parse the file as GeoJSON - check required fields (e.g. 'features') and that all coordinates are numbers.",
            )]
        )

# Reject anything that isn't a FeatureCollection, Polygon, or MultiPolygon;
# wrap a bare Polygon/MultiPolygon into a one-feature FeatureCollection so
# every step after this one only has to handle a single shape.
def normalize_root_type(geojson_data: dict) -> dict:

    root_type = geojson_data.get("type")

    if root_type == "FeatureCollection":
        return geojson_data

    if root_type in ALLOWED_GEOMETRIES:
        wrapped = {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": dict(geojson_data), "properties": {}}],
        }
        if "crs" in geojson_data:
            wrapped["crs"] = geojson_data["crs"]
        return wrapped

    raise_api_error(
        status_code=400,
        message=f"'{root_type}' is not accepted.",
        errors=[create_error(
            error_type="filter",
            message=f"Top-level type must be one of {ALLOWED_ROOT_TYPES}.",
        )]
    )

# Validate GeoJSON structure
def validate_geojson_structure(geojson_data: dict) -> dict:

    try:
        validation_results = geojson_validator.validate_structure(geojson_data)
        return validation_results or {}

    except Exception as error:
        raise_api_error(
            status_code=400,
            message="Structure Validation Error.",
            errors=[create_error(error_type="structure", message=str(error))]
        )

# Parse validation results
def parse_feature_level_issues(validation_results: dict) -> dict:

    feature_issues = {}

    if not validation_results:
        return feature_issues

    for message, details in validation_results.items():
        feature_indexes = details.get("feature") or []
        paths = details.get("path") or []
        issue_type = classify_issue(message)

        for position, feature_index in enumerate(feature_indexes):
            issue_path = paths[position] if position < len(paths) else None

            issue = create_error(error_type=issue_type, message=message, path=issue_path)

            feature_issues.setdefault(feature_index, []).append(issue)

    return feature_issues

# CRS check
def check_crs(geojson_data: dict) -> tuple[bool, dict]:

    crs_info = geojson_data.get("crs")

    if crs_info is None:
        return True, {
            "present": False,
            "name": None,
            "accepted": True,
            "value": None,
            "description": "No CRS member found. Using RFC 7946 default CRS, WGS 84 longitude/latitude."
        }

    crs_name = extract_crs_name(crs_info)
    crs_is_accepted = crs_name in ALLOWED_CRS

    return crs_is_accepted, {
        "present": True,
        "name": crs_name,
        "accepted": crs_is_accepted,
        "value": crs_info,
        "allowed_crs": ALLOWED_CRS
    }

# Get the CRS name from the GeoJSON
def extract_crs_name(crs_info: dict) -> str | None:

    if not isinstance(crs_info, dict):
        return None

    crs_properties = crs_info.get("properties", {})

    if not isinstance(crs_properties, dict):
        return None

    return crs_properties.get("name")


# Filter geometry types
def filter_geometry_types(geojson_data: dict, feature_issues: dict, allowed_geometries: list ) -> tuple[list, list]:

    accepted_features = []
    rejected_features = []

    for feature_index, feature in enumerate(geojson_data.get("features", [])):

        if feature_index in feature_issues:
            rejected_features.extend(
                create_rejected_feature_records(
                    feature_index,
                    feature,
                    feature_issues[feature_index]
                )
            )
            continue

        geometry = feature.get("geometry")

        if geometry is None:
            rejected_features.append(
                create_error(
                    feature=feature_index,
                    geometry_type=None,
                    error_type="filter",
                    message="Feature has no geometry and was skipped.",
                    properties=feature.get("properties")
                )
            )
            continue

        geometry_type = geometry.get("type")

        if geometry_type in allowed_geometries:
            accepted_features.append(feature)
        else:
            rejected_features.append(
                create_error(
                    feature=feature_index,
                    geometry_type=geometry_type,
                    error_type="filter",
                    message=f"Geometry type '{geometry_type}' is not allowed. Only Polygon and MultiPolygon are accepted.",
                    properties=feature.get("properties")
                )
            )

    return accepted_features, rejected_features

# Create error records for rejected features
def create_rejected_feature_records(feature_index: int, feature: dict, issues: list) -> list:

    rejected_records = []

    for issue in issues:
        rejected_records.append({
            **issue,
            "feature": feature_index,
            "geometry_type": None,
            "properties": feature.get("properties")
        })

    return rejected_records

# Build final response
def build_upload_response(geojson_data: dict, accepted_features: list, rejected_features: list, session_id: str ) -> dict:

    crs_is_valid, crs_status = check_crs(geojson_data)

    processed_geojson = {
        "type": "FeatureCollection",
        "features": accepted_features
    }

    errors = rejected_features[:]

    if not crs_is_valid:
        errors.append(
            create_error(
                error_type="crs",
                message=(
                    f"Unsupported CRS '{crs_status['name'] or crs_status['value']}'. "
                    f"Expected one of {', '.join(ALLOWED_CRS)}, or no CRS member."
                ),
                value=crs_status["value"]
            )
        )

    set_dataset(session_id, processed_geojson)
    set_crs_status(session_id, crs_status)

    return {
        "message": "GeoJSON uploaded successfully.",
        "valid": len(errors) == 0,
        "errors": errors,
        "summary": {
            "total_features": get_total_feature_count(geojson_data),
            "selected_features": len(accepted_features),
            "rejected_features": len(rejected_features),
        },
        "crs": crs_status,
        "processed_geojson": processed_geojson,
    }

# Get total feature count from original GeoJSON
def get_total_feature_count(geojson_data: dict) -> int:

    if geojson_data.get("type") == "FeatureCollection":
        return len(geojson_data.get("features", []))

    return 1

# Error classification based on message content
def classify_issue(message: str) -> str:

    message_lower = message.lower()

    if "coordinates" in message_lower:
        return "coordinate"

    if "type" in message_lower and "must be one of" in message_lower:
        return "type"

    return "structure"

# Create a standardized error record for API responses
def create_error(error_type: str, message: str, feature: int | None = None, path=None, geometry_type=None, properties=None, value=None ) -> dict:

    return {
        "feature": feature,
        "path": path,
        "geometry_type": geometry_type,
        "type": error_type,
        "message": message,
        "properties": properties,
        "value": value,
    }

# Raise an HTTPException with a standardized error response
def raise_api_error(status_code: int, message: str, errors: list):

    raise HTTPException(
        status_code=status_code,
        detail={"message": message, "errors": errors}
    )
