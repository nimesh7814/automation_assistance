from pyproj import Geod
from shapely.geometry import shape
from functions.session import get_dataset

# WGS84 ellipsoid - matches the lon/lat (CRS84) coordinates the app works with,
# so areas come out in real square metres instead of meaningless squared degrees.
_GEOD = Geod(ellps="WGS84")


def compute_area_hectares(geometry: dict) -> float:
    geom = shape(geometry)
    area_m2 = abs(_GEOD.geometry_area_perimeter(geom)[0])
    return area_m2 / 10_000


# Total and per-feature area in hectares for the current session
def get_area_summary(session_id: str) -> dict:
    data = get_dataset(session_id)
    features = data.get("features", [])

    per_feature = []
    total_hectares = 0.0
    for index, feature in enumerate(features):
        geometry = feature.get("geometry")
        area_hectares = None
        if geometry:
            try:
                area_hectares = round(compute_area_hectares(geometry), 4)
            except (ValueError, AttributeError, TypeError):
                area_hectares = None

        if area_hectares is not None:
            total_hectares += area_hectares

        per_feature.append({
            "feature_id": index,
            "area_hectares": area_hectares,
        })

    return {
        "total_area_hectares": round(total_hectares, 4),
        "features": per_feature,
    }
