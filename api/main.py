# Import Libraries
import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Annotated
from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

# Import functions from functions folder
from functions.upload_input import upload_geojson
from functions.validate_fix import validate_geometry, fix_geojson
from functions.duplicates import detect_duplicates
from functions.session import clear_geojson, get_session_id, sweep_idle_sessions
from functions.edit_geometry_attribute import (update_geometry_geojson, add_feature_geojson, update_properties_geojson)
from functions.delete_feature import delete_feature_geojson
from functions.export import export as export_func
from functions.get_feature import fetch_all
from functions.stats import get_area_summary


class InterceptHandler(logging.Handler):
    """Routes stdlib `logging` records (uvicorn's own logs, functions/session.py's
    sweep logger, etc.) into loguru so everything ends up on the same sinks."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


# Logging setup: console (visible via `docker compose logs` / Dozzle) plus a
# rotating file under LOG_DIR, bind-mounted to a host folder in
# docker-compose.yml so logs survive container removal, not just restarts.
LOG_DIR = os.getenv("LOG_DIR", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO, force=True)
for uvicorn_logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
    uvicorn_logger = logging.getLogger(uvicorn_logger_name)
    uvicorn_logger.handlers = [InterceptHandler()]
    uvicorn_logger.propagate = False

logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:YYYY-MM-DD HH:mm:ss} [{level}] {message}")
logger.add(
    os.path.join(LOG_DIR, "api.log"),
    level="INFO",
    rotation="5 MB",
    retention=3,
    format="{time:YYYY-MM-DD HH:mm:ss} [{level}] {message}",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    sweep_task = asyncio.create_task(sweep_idle_sessions())
    yield
    sweep_task.cancel()


# Create FastAPI app
app = FastAPI(title="GeoJSON Dashboard API", lifespan=lifespan)

# Allow the dashboard frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SessionID = Annotated[str, Depends(get_session_id)]


# Log every request with its outcome status code.
@app.middleware("http")
async def log_requests(request: Request, call_next):
    response = await call_next(request)
    logger.info(f"{request.method} {request.url.path} -> {response.status_code}")
    return response


# Give every error response the same shape
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


# Health checkpoint
@app.get("/")
def health_check():
    return {"message": "API Connected"}

# Upload & Input the GeoJSON Data
@app.post("/upload/file")
async def upload_file(session_id: SessionID, file: UploadFile = File(...)):
    return await upload_geojson(file, session_id)


# Validation of the GeoJSON Data
@app.get("/validate")
def validate(session_id: SessionID):
    return validate_geometry(session_id)

@app.post("/fix")
def fix(session_id: SessionID):
    return fix_geojson(session_id)


# Features of Given GeoJSON File
@app.get("/features")
def get_all_features(session_id: SessionID):
    return fetch_all(session_id)


# Total and per-feature area in hectares
@app.get("/stats/area")
def get_area(session_id: SessionID):
    return get_area_summary(session_id)


# Find Duplicate Geometries
@app.get("/duplicates")
def get_duplicates(
    session_id: SessionID,
    remove_duplicates: bool = Query(default=False),
    duplicate_threshold: float = Query(default=0.99, ge=0.0, le=1.0),):
    return detect_duplicates(session_id, remove_duplicates, duplicate_threshold)


# Edit Geometry of a Given Feature
@app.put("/features/{feature_id}/geometry")
async def update_geometry(feature_id: int, body: dict, session_id: SessionID):
    return update_geometry_geojson(session_id, feature_id, body.get("geometry"))

@app.put("/features/{feature_id}/properties")
async def update_properties(feature_id: int, body: dict, session_id: SessionID):
    return update_properties_geojson(session_id, feature_id, body)

@app.post("/features")
async def add_feature(body: dict, session_id: SessionID):
    return add_feature_geojson(session_id, body)


# Delete a Given Feature
@app.delete("/features/{feature_id}")
async def delete_feature(feature_id: int, session_id: SessionID):
    return delete_feature_geojson(session_id, feature_id)


# Export the final GeoJSON File
@app.get("/export")
def export(session_id: SessionID):
    return export_func(session_id)


# Clear the Imported GeoJSON Data
@app.delete("/data")
def session_reset(session_id: SessionID):
    return clear_geojson(session_id)
