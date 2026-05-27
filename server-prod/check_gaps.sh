#!/bin/bash
DB=~/smart-garden-server/smart-garden.db
echo "=== DHT22 rows (24h) ==="
sqlite3 "$DB" "SELECT COUNT(*), MIN(ts), MAX(ts) FROM weather_log WHERE source='dht22' AND ts >= datetime('now','localtime','-24 hours')"

echo ""
echo "=== DHT22 gaps > 10 min ==="
sqlite3 "$DB" "
WITH ordered AS (
  SELECT ts, LAG(ts) OVER (ORDER BY ts) as prev_ts
  FROM weather_log
  WHERE source='dht22' AND ts >= datetime('now','localtime','-24 hours')
)
SELECT prev_ts, ts, ROUND((julianday(ts)-julianday(prev_ts))*1440) as gap_min
FROM ordered
WHERE prev_ts IS NOT NULL AND (julianday(ts)-julianday(prev_ts))*1440 > 10
ORDER BY ts"

echo ""
echo "=== system_health rows (24h) ==="
sqlite3 "$DB" "SELECT COUNT(*), MIN(ts), MAX(ts) FROM system_health WHERE ts >= datetime('now','localtime','-24 hours')"

echo ""
echo "=== system_health gaps > 10 min ==="
sqlite3 "$DB" "
WITH ordered AS (
  SELECT ts, LAG(ts) OVER (ORDER BY ts) as prev_ts
  FROM system_health
  WHERE ts >= datetime('now','localtime','-24 hours')
)
SELECT prev_ts, ts, ROUND((julianday(ts)-julianday(prev_ts))*1440) as gap_min
FROM ordered
WHERE prev_ts IS NOT NULL AND (julianday(ts)-julianday(prev_ts))*1440 > 10
ORDER BY ts"
