from fastapi import HTTPException
from functions.session import get_dataset

# Delete a feature by its index
def delete_feature_geojson(session_id: str, feature_id: int):

    data = get_dataset(session_id)
    features = data["features"]

    # Check the feature_id is within range
    if feature_id < 0 or feature_id >= len(features):
        raise HTTPException(status_code=404, detail=f"Feature {feature_id} not found. Valid range is 0 to {len(features) - 1}.")

    # Remove the feature
    removed = features.pop(feature_id)

    return {
        "message": f"Feature {feature_id} deleted successfully.",
        "deleted_feature": removed,
        "total_features": len(features)
    }