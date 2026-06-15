from fastapi import HTTPException
from functions.session import is_data_here


def get_all_features():
    
    # Check something is loaded in the session
    data = is_data_here()
    features = data["features"]

    # Return all features with a count
    return {
        "total_features": len(features),
        "features": features
    }


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
