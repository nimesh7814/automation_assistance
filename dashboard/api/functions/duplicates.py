import math
from shapely import wkt as shapely_wkt
from shapely.geometry import shape
from functions.session import get_dataset


# Solve the issue of NaN values in the duplicate group numbers by converting them to None
def clean_group_number(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return int(value)

# Detect duplicate geometries based on their rounded WKT representations
def detect_duplicates(session_id: str, remove_duplicates: bool = False, duplicate_threshold: float = 0.99):
    data = get_dataset(session_id)
    features = data["features"]
    total_before = len(features)

    # Build a shapely geometry for each feature, fixing small invalidities where possible.
    geometries = []
    geometry_types = []
    for feature in features:
        geometry_dict = feature.get("geometry") or {}
        geometry_types.append(geometry_dict.get("type"))

        try:
            geom = shape(geometry_dict)
            if not geom.is_valid:
                geom = geom.buffer(0)
            if geom.is_empty:
                geom = None
        except (ValueError, AttributeError, TypeError):
            geom = None

        geometries.append(geom)

    # Duplicate threshold is used to determine how precisely the shapes must match
    decimal_places = int(duplicate_threshold * 10)
    rounded_wkts = [
        shapely_wkt.dumps(geom, rounding_precision=decimal_places) if geom is not None else None
        for geom in geometries
    ]

    # Count how many features share each rounded shape
    wkt_counts = {}
    for wkt in rounded_wkts:
        if wkt is not None:
            wkt_counts[wkt] = wkt_counts.get(wkt, 0) + 1

    # Give each shape that appears more than once a duplicate group number
    group_numbers = {}
    next_group_number = 1
    for wkt, count in wkt_counts.items():
        if count > 1:
            group_numbers[wkt] = next_group_number
            next_group_number += 1

    # Mark every feature after the first one in a group as a duplicate
    seen_wkts = set()
    is_duplicate = []
    for wkt in rounded_wkts:
        if wkt is not None and wkt in group_numbers and wkt in seen_wkts:
            is_duplicate.append(True)
        else:
            is_duplicate.append(False)
            if wkt is not None:
                seen_wkts.add(wkt)

    duplicate_count = sum(is_duplicate)
    group_count = len(group_numbers)

    feature_summaries = []
    for index, feature in enumerate(features):
        feature_summaries.append({
            "feature_id": index,
            "properties": feature.get("properties"),
            "geometry_type": geometry_types[index],
            "geometry_valid": geometries[index] is not None,
            "is_duplicate": int(is_duplicate[index]),
            "duplicate_group": clean_group_number(group_numbers.get(rounded_wkts[index])),
        })

    # Remove duplicate features from the session if requested
    if remove_duplicates and duplicate_count:
        for index in reversed(range(len(features))):
            if is_duplicate[index]:
                features.pop(index)
                feature_summaries.pop(index)

        # Re-number the remaining features to match their new positions.
        for new_index, summary in enumerate(feature_summaries):
            summary["feature_id"] = new_index

    return {
        "total_features_before": total_before,
        "duplicate_groups_found": group_count,
        "duplicates_removed": duplicate_count if remove_duplicates else 0,
        "total_features_after": len(features),
        "features": feature_summaries,
    }
