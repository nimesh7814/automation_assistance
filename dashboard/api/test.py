import json
import tempfile
import geojson_validator


test_geojson = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [80.0, 7.0],
                        [81.0, 7.0],
                        [81.0, 8.0],
                        [80.0, 7.0]
                    ]
                ]
            },
            "properties": {"id": 1}
        },
        {
            "type": "Feature",
            "properties": {"id": 2}
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "Circle",
                "coordinates": []
            },
            "properties": {"id": 3}
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": "INVALID_COORDINATES"
            },
            "properties": {"id": 4}
        },
        {
            "type": "Feature",
            "geometry": None,
            "properties": {"id": 5}
        },
        {
            "type": "Feature",
            "geometry": {
                "features": [
                    {"type": "Feature"}
                ]
            },
            "properties": {"id": 6}
        }
    ]
}


# ---- FIXED TEMP FILE HANDLING ----
with tempfile.NamedTemporaryFile(mode="w", suffix=".geojson", delete=False) as f:
    json.dump(test_geojson, f)
    temp_path = f.name  # store path AFTER closing

# NOW file is closed → safe for validator
try:
    result = geojson_validator.validate_structure(temp_path)
    print("RESULT:", result)
except Exception as e:
    print("ERROR:", e)