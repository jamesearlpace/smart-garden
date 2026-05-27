import sys
sys.path.insert(0, '/home/jamesearlpace/smart-garden-server')
import database as db
db.init_db()
import yaml
cfg = yaml.safe_load(open('/home/jamesearlpace/smart-garden-server/config.yaml'))
from weather import WeatherClient
from billing import BillingCalculator
from irrigation import IrrigationEngine
w = WeatherClient(
    lat=cfg["location"]["lat"],
    lon=cfg["location"]["lon"],
    timezone=cfg["location"]["timezone"],
)
b = BillingCalculator(cfg)
e = IrrigationEngine(cfg, w, b)
e.save_daily_forecast_snapshot()
rows = db.get_forecast_vs_actual(7)
print(f"{len(rows)} rows in forecast_vs_actual")
for r in rows:
    zn = r["zone_name"]
    pd = r["predicted_days"]
    oc = r["outcome"]
    print(f"  {zn}: predicted_days={pd}, outcome={oc}")
