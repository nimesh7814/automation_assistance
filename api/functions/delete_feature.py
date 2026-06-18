from functions.session import check_feature_id, get_dataset

# Delete a feature by its index
def delete_feature_geojson(session_id: str, feature_id: int):

    data = get_dataset(session_id)
    features = data["features"]
    check_feature_id(feature_id, features)

    # Remove the feature
    removed = features.pop(feature_id)

    return {
        "message": f"Feature {feature_id} deleted successfully.",
        "deleted_feature": removed,
        "total_features": len(features)
    }
