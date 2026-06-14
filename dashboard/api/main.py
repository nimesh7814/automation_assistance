# Import Libraries
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import json
from geojason import (
    fix_geojson, process_geojson, validate_geojson,
    detect_duplicates, is_data_here, update_geometry_geojson,
    add_feature_geojson, delete_feature_geojson, update_properties_geojson,
    undo_geojson, export_geojson
)
from fastapi.responses import JSONResponse
from fastapi import Query

# Create FastAPI app
app = FastAPI(title="GeoJSON Dashboard API")

# Keep a history of changes for the Undo functionality
undo_history = []


# Upload & Input the GeoJSON Data
@app.post("/upload/file")
async def upload_file(file: UploadFile = File(...)):
    
    # Read the uploaded file
    contents = await file.read()
    
    # Validate the file content as JSON
    try:
        data = json.loads(contents.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="File is not valid JSON.")

    # Print the Output
    return process_geojson(data)

@app.post("/upload/text")
async def upload_text(body: dict):
    
    # Print the result
    return process_geojson(body)


# Validation of the GeoJSON Data
@app.get("/validate")
def validate():
    return validate_geojson()

@app.post("/fix")
def fix():
    return fix_geojson(undo_history)


# Features of Given GeoJSON File
@app.get("/features")
def get_all_features():

    # Check something is loaded in the session
    data = is_data_here()

    features = data["features"]

    # Return all features with a count
    return {
        "total_features": len(features),
        "features": features
    }

@app.get("/features/{feature_id}")
def get_single_feature(feature_id: int):

    data = is_data_here()

    features = data["features"]

    # Check the feature_id is within range
    if feature_id < 0 or feature_id >= len(features):
        raise HTTPException(status_code=404, detail=f"Feature {feature_id} not found. Valid range is 0 to {len(features) - 1}.")

    # Return the single feature
    return {
        "feature_id": feature_id,
        "feature": features[feature_id]
    }


# Find Duplicate Geometries
@app.get("/duplicates")
def get_duplicates(remove_duplicates: bool = Query(default=False)):
    return detect_duplicates(remove_duplicates)


# Edit Geometry of a Given Feature
@app.put("/features/{feature_id}/geometry")
async def update_geometry(feature_id: int, body: dict):
    return update_geometry_geojson(feature_id, body.get("geometry"), undo_history)

@app.post("/features")
async def add_feature(body: dict):
    return add_feature_geojson(body, undo_history)

@app.delete("/features/{feature_id}")
def delete_feature(feature_id: int):
    return delete_feature_geojson(feature_id, undo_history)


# Edit Attributes of a Given Feature
@app.put("/features/{feature_id}/properties")
async def update_properties(feature_id: int, body: dict):
    return update_properties_geojson(feature_id, body, undo_history)


# Undo the Changes Made to the GeoJSON Data
@app.post("/undo")
def undo():
    return undo_geojson(undo_history)


# Export the final GeoJSON File
@app.get("/export")
def export():
    data = export_geojson()
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": "attachment; filename=export.geojson"}
    )