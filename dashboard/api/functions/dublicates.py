from shapely.geometry import shape
from functions.session import is_data_here


def detect_duplicates(remove_duplicates: bool = False):
    
    data = is_data_here()
    features = data["features"]

    # Build shapely geometries once for comparison. Geometries that fail to
    # parse are treated as never matching anything.
    geometries = []
    for feature in features:
        try:
            geometries.append(shape(feature.get("geometry")))
        except (ValueError, AttributeError, TypeError):
            geometries.append(None)

    # Group feature indices whose geometries are topologically identical —
    # this catches duplicates even when vertex order, winding direction or
    # the starting point differ, unlike a plain string/coordinate comparison.
    # position 0 = kept copy, position 1+ = duplicates to remove
    duplicate_group_map = {}
    group_number = 1
    matched = set()
    for i in range(len(geometries)):
        if i in matched or geometries[i] is None:
            continue
        group_indices = [i]
        for j in range(i + 1, len(geometries)):
            if j in matched or geometries[j] is None:
                continue
            if geometries[i].equals(geometries[j]):
                group_indices.append(j)
                matched.add(j)
        if len(group_indices) > 1:
            for position, index in enumerate(group_indices):
                duplicate_group_map[index] = {
                    "group": group_number,
                    "is_duplicate": 0 if position == 0 else 1
                }
            group_number += 1

    # Indices to remove — only the copies, not the first occurrence
    indices_to_remove = [
        index for index, info in duplicate_group_map.items()
        if info["is_duplicate"] == 1
    ]

    # Build the feature list with flags
    features_with_flag = []
    for index, feature in enumerate(features):
        group_info = duplicate_group_map.get(index)
        features_with_flag.append({
            "feature_id": index,
            "is_duplicate": group_info["is_duplicate"] if group_info else 0,
            "duplicate_group": group_info["group"] if group_info else None,
            "properties": feature.get("properties"),
            "geometry_type": feature.get("geometry", {}).get("type")
        })

    # Only remove if explicitly requested
    if remove_duplicates and indices_to_remove:

        # Remove in reverse order so indices don't shift
        for index in sorted(indices_to_remove, reverse=True):
            data["features"].pop(index)

        # Rebuild the flag list — only kept features, clean duplicate_group to null
        features_with_flag = []
        for new_id, feature in enumerate(data["features"]):
            features_with_flag.append({
                "feature_id": new_id,
                "is_duplicate": 0,
                "duplicate_group": None,   # ← now null since duplicates are gone
                "properties": feature.get("properties"),
                "geometry_type": feature.get("geometry", {}).get("type")
            })

    return {
        "total_features_before": len(features) + len(indices_to_remove) if remove_duplicates else len(features),
        "duplicate_groups_found": group_number - 1,
        "removed": len(indices_to_remove) if remove_duplicates else 0,
        "total_features_after": len(data["features"]),
        "features": features_with_flag
    }
