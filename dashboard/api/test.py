import geojson

VALID_TYPES = ("Polygon", "MultiPolygon")

# FeatureCollection with every geometry type
geojson_string = '''
{
    "type": "MultiPolygon",
    "coordinates": [
        [
            [
                [-75.445, 5.639],
                [-75.446, 5.640],
                [-75.447, 5.639],
                [-75.446, 5.638],
                [-75.445, 5.639]
            ]
        ],
        [
            [
                [-75.500, 5.700],
                [-75.510, 5.710],
                [-75.520, 5.700],
                [-75.510, 5.690],
                [-75.500, 5.700]
            ]
        ]
    ]
}
'''



def verify(geojson_string: str):

    # Parse the string
    data = geojson.loads(geojson_string)

    print(data)

    top_type = data.get("type")

    # FeatureCollection — check each feature
    if top_type == "FeatureCollection":

        valid = []
        rejected = []

        for index, feature in enumerate(data["features"]):
            geom_type = feature.get("geometry", {}).get("type")
            name = feature.get("properties", {}).get("name")

            if geom_type in VALID_TYPES:
                valid.append(feature)
                print(f"  ✓ Feature {index} — {geom_type:<20} — {name}")
            else:
                rejected.append(feature)
                print(f"  ✗ Feature {index} — {geom_type:<20} — {name} — rejected")

        print(f"\nAccepted : {len(valid)} polygon feature(s)")
        print(f"Rejected : {len(rejected)} non-polygon feature(s)")

    # Bare Polygon or MultiPolygon
    elif top_type in VALID_TYPES:
        print(f"Valid — {top_type}")

    # Anything else
    else:
        print(f"Rejected — '{top_type}' is not accepted.")


verify(geojson_string)