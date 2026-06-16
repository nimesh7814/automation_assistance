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
