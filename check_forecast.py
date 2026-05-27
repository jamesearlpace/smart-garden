import yaml, sys
sys.path.insert(0, ".")
import database as db

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

for z in cfg["zones"]:
    if not z.get("installed", False):
        continue
    b = db.get_soil_balance(z["id"])
    if b:
        taw = b.get("taw_mm", 10)
        bal = b["balance_mm"]
        pct = (bal / taw * 100) if taw > 0 else 0
        etc = b.get("etc_mm", 0)
        mad = b.get("mad_mm", 5)
        threshold = taw - mad
        if etc > 0 and bal > threshold:
            days = (bal - threshold) / etc
        elif bal <= threshold:
            days = 0
        else:
            days = None
        days_str = f"{days:.1f}" if days is not None else "?"
        print(f"Zone {z['id']+1} ({z['name']}): balance={bal:.1f}/{taw:.1f}mm ({pct:.0f}%), ETc={etc:.2f}mm/day, MAD threshold={threshold:.1f}mm, days_until_water={days_str}")
    else:
        print(f"Zone {z['id']+1} ({z['name']}): no balance data")
