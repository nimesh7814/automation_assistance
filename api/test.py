import geopandas as gpd

input_file = r"D:\Work\Github\automation_assistance\dashboard\data\Farm_file.geojson"
gdf = gpd.read_file(input_file)

print("Original features:", len(gdf))

gdf["wkt"] = gdf.geometry.apply(lambda x: x.wkt)
gdf = gdf.drop_duplicates(subset="wkt").drop(columns=["wkt"])

print("After exact duplicate removal:", len(gdf))

gdf["geometry"] = gdf.geometry.simplify(tolerance=0.01, preserve_topology=True)

gdf["wkt"] = gdf.geometry.apply(lambda x: x.wkt)
gdf = gdf.drop_duplicates(subset="wkt").drop(columns=["wkt"])

print("After simplification + duplicate removal:", len(gdf))

gdf.to_file("cleaned_example.geojson", driver="GeoJSON")