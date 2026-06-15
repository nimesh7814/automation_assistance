from fastapi import HTTPException
from functions.session import get_dataset

# Fetch all features in the current session
def fetch_all():

    # Check something is loaded in the session
    data = get_dataset()
    features = data["features"]

    # Return all features with a count
    return {
        "total_features": len(features),
        "features": features
    }

# Fetch a single feature by its index
def get_single_feature(feature_id: int):

    data = get_dataset()
    features = data["features"]

    # Check the feature_id is within range
    if feature_id < 0 or feature_id >= len(features):
        raise HTTPException(status_code=404, detail=f"Feature {feature_id} not found. Valid range is 0 to {len(features) - 1}.")

    # Return the single feature
    return {
        "feature_id": feature_id,
        "feature": features[feature_id]
    }
