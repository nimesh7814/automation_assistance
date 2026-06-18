from functions.session import get_crs_status, get_dataset

# Fetch all features in the current session
def fetch_all(session_id: str):

    # Check something is loaded in the session
    data = get_dataset(session_id)
    features = data["features"]

    # Return all features with a count
    return {
        "total_features": len(features),
        "features": features,
        "crs": get_crs_status(session_id),
    }
