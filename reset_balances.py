import yaml, sys
from datetime import date
sys.path.insert(0, ".")
import database as db

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

today = date.today().isoformat()
for z in cfg["zones"]:
    zid = z["id"]
    if not z.get("installed", False):
        continue
    # Reset balance to field capacity (TAW)
    awc = cfg.get("soil", {}).get("awc_in_per_in", 0.15)
    root = z.get("root_depth_in", 6)
    mad_pct = cfg.get("soil", {}).get("default_mad_pct", 50)
    taw_mm = awc * root * 25.4
    mad_mm = taw_mm * mad_pct / 100
    db.upsert_soil_balance(
        zone_id=zid, day=today, et0_mm=0, kc=0,
        etc_mm=0, rain_mm=0, irrigation_mm=0,
        balance_mm=taw_mm, taw_mm=taw_mm, mad_mm=mad_mm
    )
    print(f"Zone {zid+1}: reset to {taw_mm:.1f}mm (field capacity)")
