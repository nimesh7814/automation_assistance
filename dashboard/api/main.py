from fastapi import FastAPI, UploadFile, File, HTTPException
import json
from pyproj import Transformer, CRS


# Handle the CRS transformation
def extract_crs(geojson_data):
    if "crs" not in geojson_data:
        return "EPSG:4326"
    crs_obj = geojson_data["crs"]
    if isinstance(crs_obj, dict):
        return crs_obj.get("properties", {}).get("name", "EPSG:4326")
    return "EPSG:4326"


def normalize_crs(crs_string):
    crs = CRS.from_user_input(crs_string)
    epsg = crs.to_epsg()
    if epsg:
        return f"EPSG:{epsg}"
    return crs_string


# Reproject coordinates
def reproject_coords(coords, transformer):
    if isinstance(coords[0], (int, float)):
        x, y = transformer.transform(coords[0], coords[1])
        return [x, y]
    return [reproject_coords(c, transformer) for c in coords]



# Establish the FastAPI app
app = FastAPI(title="GeoJSON API", description="A simple API to serve GeoJSON data to a Map", version="1.0.0")

# Health Check Endpoint
@app.get("/")
async def health_check():
    return {"status": "ok"}

# Upload GeoJSON Endpoint
@app.post("/upload-geojson")
async def upload_geojson(file: UploadFile = File(...)):
    
    # Check the file extension
    if not file.filename.endswith('.geojson'):
        raise HTTPException(status_code=400, detail="Only GeoJSON files are allowed.")
    
    # Read the content and parse as JSON
    content = await file.read()
    geojson_data = json.loads(content.decode("utf-8"))
    
    # Make sure the GeoJSON has 'features'
    if "features" not in geojson_data:
        raise HTTPException(status_code=400, detail="Invalid GeoJSON format: 'features' key is missing.")
    
    # Check the Coordinate System (CRS)
    input_crs = normalize_crs(extract_crs(geojson_data))
    target_crs = "EPSG:4326"

    if input_crs != target_crs:
        transformer = Transformer.from_crs(input_crs, target_crs, always_xy=True)

        for feature in geojson_data["features"]:
            geom = feature.get("geometry")
            if geom and "coordinates" in geom:
                geom["coordinates"] = reproject_coords(geom["coordinates"], transformer)

    return {
        "status": "success",
        "input_crs": input_crs,
        "output_crs": target_crs,
        "features_count": len(geojson_data["features"]),
        "geojson": geojson_data
    }