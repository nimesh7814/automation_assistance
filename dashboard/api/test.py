import geojson_validator
import json

criteria_invalid = [
    "unclosed",
    "less_three_unique_nodes",
    "exterior_not_ccw",
    "interior_not_cw",
    "inner_and_exterior_ring_intersect"
]

content = '{"type":"Feature","geometry":{"type":"Point","coordinates":[80.63,7.29]},"properties":{}}'

geojson_input = json.loads(content)

geojson_validator.validate_structure(geojson_input)
geojson_validator.validate_geometries(geojson_input, criteria_invalid)