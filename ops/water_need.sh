#!/bin/bash
cd ~/smart-garden-server
echo '=== current actual delivery per zone, last 14 days ==='
sqlite3 -header smart-garden.db "SELECT zone_id, COUNT(*) runs, ROUND(SUM(est_gallons),0) tot_gal_14d, ROUND(SUM(est_gallons)/2.0,0) gal_per_week, COUNT(DISTINCT date(start_ts)) days_watered FROM watering_event WHERE start_ts >= '2026-06-25' AND end_ts IS NOT NULL AND zone_id BETWEEN 0 AND 6 GROUP BY zone_id ORDER BY zone_id;"
echo
echo '=== WATER-NEED MODEL ==='
./.venv/bin/python - <<'PY'
# Measured median GPM per zone (from zone_flow_est)
gpm = {0:5.01, 1:5.52, 2:7.33, 3:8.20, 4:5.00, 5:4.33, 6:4.55}
heads = {0:4, 1:4, 2:3, 3:3, 4:4, 5:3, 6:4}
names = {0:"Front Yard A",1:"Front Yard B",2:"Enclosed Back A (trees)",3:"Enclosed Back B (garden side)",4:"Southeast",5:"South",6:"Southwest"}
# current avg gal per week (last 14d) - fill from query above after seeing it; placeholder computed live not here
SPACING = 30.0          # ft, head-to-head
AREA_PER_HEAD = SPACING*SPACING   # 900 sq ft (square head-to-head)
GAL_PER_SQFT_PER_INCH = 0.623
TARGET_IN_WK = 1.5      # summer PNW lawn, deep; brown -> aim high end
print(f"assume {AREA_PER_HEAD:.0f} sqft/head (30ft square head-to-head)")
print(f"{'zone':4} {'name':28} {'heads':>5} {'area':>6} {'gpm':>5} {'PR in/hr':>8} {'need gal/wk':>11} {'need min/wk':>11} {'min/day(x3)':>11}")
for z in range(7):
    a = heads[z]*AREA_PER_HEAD
    g = gpm[z]
    pr = 96.25*g/a                      # effective precip rate in/hr
    need_gal_wk = a*TARGET_IN_WK*GAL_PER_SQFT_PER_INCH
    need_min_wk = need_gal_wk/g
    per_day3 = need_min_wk/3.0          # if watering 3 days/week
    print(f"{z:<4} {names[z]:28} {heads[z]:>5} {a:>6.0f} {g:>5.1f} {pr:>8.3f} {need_gal_wk:>11.0f} {need_min_wk:>11.0f} {per_day3:>11.0f}")
PY
