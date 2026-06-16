# Import Libraries
import logging
from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Import functions from functions folder
from functions.upload_input import upload_geojson
from functions.validate_fix import validate_geometry, fix_geojson
from functions.duplicates import detect_duplicates
from functions.session import clear_geojson
from functions.edit_geometry_attribute import (update_geometry_geojson, add_feature_geojson, update_properties_geojson)
from functions.delete_feature import delete_feature_geojson
from functions.export import export as export_func
from functions.get_feature import fetch_all

# Basic logging setup (console)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("geojson_dashboard")

# Create FastAPI app
app = FastAPI(title="GeoJSON Dashboard API")

# Allow the dashboard frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Log every request with its outcome status code.
@app.middleware("http")
async def log_requests(request: Request, call_next):
    response = await call_next(request)
    logger.info(f"{request.method} {request.url.path} -> {response.status_code}")
    return response


# Give every error response the same shape: {"message": ..., "errors": [...]}
@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException):
    detail = exc.detail

    if isinstance(detail, dict):
        message = detail.get("message", "Request failed.")
        errors = detail.get("errors", [])
    else:
        message = str(detail)
        errors = []

    return JSONResponse(
        status_code=exc.status_code,
        content={"message": message, "errors": errors},
    )


# Catch anything that isn't already an HTTPException
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, _exc: Exception):
    logger.exception(f"Unhandled error on {request.method} {request.url.path}")
    return JSONResponse(
        status_code=500,
        content={"message": "Something went wrong while processing your request.", "errors": []},
    )


# Upload & Input the GeoJSON Data
@app.post("/upload/file")
async def upload_file(file: UploadFile = File(...)):
    return await upload_geojson(file)


# Validation of the GeoJSON Data
@app.get("/validate")
def validate():
    return validate_geometry()

@app.post("/fix")
def fix():
    return fix_geojson()


# Features of Given GeoJSON File
@app.get("/features")
def get_all_features():
    return fetch_all()


# Find Duplicate Geometries
@app.get("/duplicates")
def get_duplicates(
    remove_duplicates: bool = Query(default=False),
    duplicate_threshold: float = Query(default=0.99, ge=0.0, le=1.0),):
    return detect_duplicates(remove_duplicates, duplicate_threshold)


# Edit Geometry of a Given Feature
@app.put("/features/{feature_id}/geometry")
async def update_geometry(feature_id: int, body: dict):
    return update_geometry_geojson(feature_id, body.get("geometry"))

@app.put("/features/{feature_id}/properties")
async def update_properties(feature_id: int, body: dict):
    return update_properties_geojson(feature_id, body)

@app.post("/features")
async def add_feature(body: dict):
    return add_feature_geojson(body)


# Delete a Given Feature
@app.delete("/features/{feature_id}")
async def delete_feature(feature_id: int):
    return delete_feature_geojson(feature_id)


# Export the final GeoJSON File
@app.get("/export")
def export():
    return export_func()


# Clear the Imported GeoJSON Data
@app.delete("/data")
def session_reset():
    return clear_geojson()