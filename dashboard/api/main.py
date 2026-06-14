# Import Libraries
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import json
from geojason import geojson_dataset, process_geojson, validate_geojson, fix_geojson

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
    return fix_geojson()


# # Features of Given GeoJSON File
# @app.get("/features")
# def get_all_features():
#     """Return all polygon features with their attributes for the map and attribute table."""
#     pass

# @app.get("/features/{feature_id}")
# def get_single_feature(feature_id: int):
#     """Return one feature by id — triggers the editable vertices view on the map."""
#     pass


# # Find Duplicate Geometries
# @app.get("/duplicates")
# def detect_duplicates():
#     """Scan all features and flag any duplicated geometries in the attribute table."""
#     pass


# # Edit Geometry of a Given Feature
# @app.put("/features/{feature_id}/geometry")
# async def update_geometry(feature_id: int, body: dict):
#     """Save the updated geometry after the user moves vertices on the map."""
#     pass

# @app.post("/features")
# async def add_feature(body: dict):
#     """Save a newly drawn polygon and its attributes to the session store."""
#     pass

# @app.delete("/features/{feature_id}")
# def delete_feature(feature_id: int):
#     """Remove a feature from the session store by its id."""
#     pass


# # Edit Attributes of a Given Feature
# @app.put("/features/{feature_id}/properties")
# async def update_properties(feature_id: int, body: dict):
#     """Update the attribute fields of a feature from the attribute table."""
#     pass


# # Undo the Changes Made to the GeoJSON Data
# @app.post("/undo")
# def undo():
#     """Revert the last change made — geometry edit, attribute edit, add, or delete."""
#     pass


# # Export the final GeoJSON File
# @app.get("/export")
# def export_geojson():
#     """Package the current session store and return it as a downloadable .geojson file."""
#     pass
