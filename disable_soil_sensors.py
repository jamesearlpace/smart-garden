import yaml
path = "/home/jamesearlpace/smart-garden-server/config.yaml"
with open(path) as f:
    cfg = yaml.safe_load(f)
for z in cfg["zones"]:
    z["soil_sensor"] = None
cfg["sensors"]["soil_0"] = False
cfg["sensors"]["soil_1"] = False
cfg["sensors"]["soil_2"] = False
cfg["sensors"]["soil_3"] = False
with open(path, "w") as f:
    yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
print("Done: all soil sensors disabled, ET/weather scheduling only.")
