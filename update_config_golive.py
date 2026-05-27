"""Update config.yaml for go-live."""
import yaml

with open("/home/jamesearlpace/smart-garden-server/config.yaml") as f:
    cfg = yaml.safe_load(f)

for z in cfg["zones"]:
    # Rename Garden and Grapes
    if z["id"] == 7:
        z["name"] = "Garden"
        z["description"] = "Vegetable garden drip"
    elif z["id"] == 8:
        z["name"] = "Grapes"
        z["description"] = "Grape vine drip"
    # Disable spare
    elif z["id"] == 9:
        z["installed"] = False

    # Update GPM: 1 GPM per head for sprinkler zones
    if z["type"] == "sprinkler" and z.get("heads", 0) > 0:
        z["est_gpm"] = float(z["heads"]) * 1.0

# Evening zones = Garden (id 7) and Grapes (id 8)
cfg["watering_window"]["evening_zones"] = [7, 8]

with open("/home/jamesearlpace/smart-garden-server/config.yaml", "w") as f:
    yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)

print("Done: renamed zones 8→Garden, 9→Grapes, disabled zone 10, updated GPM to 1/head, fixed evening zones")
