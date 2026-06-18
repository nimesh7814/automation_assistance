import geojson
import geojson_validator
from json import JSONDecodeError
from loguru import logger

logger.remove()

filepath = r"D:\Work\Github\automation_assistance\sample_data\Farm_file.geojson"

ALLOWED_GEOMETRIES = ["Polygon", "MultiPolygon"]
ALLOWED_CRS = "urn:ogc:def:crs:OGC:1.3:CRS84"

# Load the GeoJSON file and handle potential errors
def load_geojson_file(file_path):

    try:
        with open(file_path, "r", encoding="utf-8") as opened_file:
            parsed_geojson = geojson.load(opened_file)

        return parsed_geojson

    except UnicodeDecodeError:
        print("Unicode Error: File must be UTF-8 encoded.")
        return None

    except JSONDecodeError as error:
        print(f"JSON Error: File is not valid JSON. "f"{error.msg} (line {error.lineno}, column {error.colno})")
        return None

    except Exception as error:
        print("Unexpected Error: " + str(error))
        return None

# Print validation errors in a clear and structured format
def print_errors(validation_results):

    print("Structure Validation Errors:\n")

    for error_number, (error_message, error_details) in enumerate(validation_results.items(),start=1):
        
        error_path = error_details.get("path", [])

        if error_path == [""]:
            readable_location = "root object"
        else:
            readable_location = " → ".join(str(path_part) for path_part in error_path)

        print(f"Error {error_number}:")
        print(f"  Message : {error_message}")
        print(f"  Location: {readable_location}")
        print()

# Validate the structure of the GeoJSON data and print any errors
def validate_geojson_structure(parsed_geojson):

    try:
        validation_results = geojson_validator.validate_structure(parsed_geojson)

        if validation_results:
            print_errors(validation_results)
        else:
            print("GeoJSON structure is valid.")

        return validation_results

    except Exception as error:
        print("Unexpected Validation Error: " + str(error))
        return None

# Check the CRS
def check_crs(parsed_geojson, allowed_crs):

    crs_info = parsed_geojson.get("crs")

    if crs_info is None:
        print("CRS is valid.")
        print("  Description: No CRS member found. Assuming standard GeoJSON CRS.")
        print(f"  Assumed CRS: {allowed_crs}\n")
        return True

    crs_name = None

    if isinstance(crs_info, dict):
        crs_properties = crs_info.get("properties", {})

        if isinstance(crs_properties, dict):
            crs_name = crs_properties.get("name")

    if crs_name == allowed_crs:
        print("CRS is valid.")
        print(f"  CRS: {crs_name}\n")
        return True

    print("CRS Issue Found:")
    print(f"  Found CRS   : {crs_name}")
    print(f"  Allowed CRS: {allowed_crs}")
    print(f"  CRS Object  : {crs_info}")
    print("  Description : CRS must be absent or exactly match the allowed CRS.\n")
    
    return False

# Filter the Geometry types in the GeoJSON data
def filter_geometry_types(parsed_geojson, geometry_types):

    filtered_features = []

    for feature in parsed_geojson.get("features", []):
        geometry = feature.get("geometry")

        if geometry is None:
            continue

        geometry = geometry.get("type")

        if geometry in geometry_types:
            filtered_features.append(feature)

    return filtered_features

# Load the GeoJSON file
loaded_geojson = load_geojson_file(filepath)

if loaded_geojson is not None:
    structure_validation_results = validate_geojson_structure(loaded_geojson)

    crs_is_valid = check_crs(loaded_geojson, ALLOWED_CRS)

    filtered_features = filter_geometry_types(
        loaded_geojson,
        ALLOWED_GEOMETRIES
    )

    print(f"Filtered feature count: {len(filtered_features)}")

    filtered_geojson = {
        "type": "FeatureCollection",
        "features": filtered_features
    }

    validated_geometries = geojson_validator.validate_geometries(filtered_geojson)

    print("Geometry validation results:")
    print(validated_geometries)