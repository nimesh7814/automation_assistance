import geojson
import geojson_validator

data = r"D:\Work\Github\automation_assistance\sample_data\all_errors_combined.geojson"

print("Validation Test 01...\n")
try:
    with open(data, 'r', encoding="utf-8") as f:
        geojson_data = geojson.load(f)

except Exception as e:
    print(f"Error: {e}")
    

print("\nValidation Test 02...\n")
try:
    geojson_validator.validate_structure(data)
except Exception as e:
    print(f"Error: {e}")
