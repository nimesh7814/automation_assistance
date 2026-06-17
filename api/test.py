import geojson

data = r"D:\Work\Github\automation_assistance\sample_data\Test_Farm.geojson"

try:
    with open(data, 'r', encoding="utf-8") as f:
        geojson_data = geojson.load(f)

except Exception as e:
    print(f"Error: {e}")