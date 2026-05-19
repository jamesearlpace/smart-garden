#!/bin/bash
cd ~/smart-garden-server

# 1. Insert fresh_valves() helper after cached_valves() (after line 73)
sed -i '73a\
\
    def fresh_valves():\
        """Fetch live valve state from ESP32 after a manual toggle."""\
        status = engine.get_esp32_status(force_fresh=True)\
        return (status or {}).get("valves", [])' dashboard.py

# 2. In api_valve response: use fresh_valves() when command succeeded
sed -i '/"valves": cached_valves(),/{s/cached_valves()/fresh_valves() if ok else cached_valves()/}' dashboard.py

# 3. In api_closeall response: same fix
sed -i '/"valves": cached_valves()}/{s/cached_valves()/fresh_valves() if ok else cached_valves()/}' dashboard.py

echo "=== Verification ==="
grep -n 'fresh_valves\|cached_valves' dashboard.py
