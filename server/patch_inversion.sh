#!/bin/bash
cd ~/smart-garden-server

# 1. Add zone_inverted() helper after zone_installed()
sed -i '/return bool(config\["zones"\]\[zone_id\]\.get("installed", False))/a\
\
    def zone_inverted(zone_id):\
        if zone_id < 0 or zone_id >= len(config["zones"]):\
            return False\
        return bool(config["zones"][zone_id].get("inverted", False))\
\
    def apply_inversion(valves):\
        """Flip open flag for zones with inverted wiring."""\
        import copy\
        result = copy.deepcopy(valves)\
        for i, v in enumerate(result):\
            if zone_inverted(i):\
                v["open"] = not v["open"]\
        return result' dashboard.py

# 2. Update cached_valves to apply inversion
sed -i 's/return (status or {}).get("valves", \[\])$/\0/' dashboard.py
# Replace cached_valves body
sed -i '/def cached_valves/,/return (status or {}).get("valves", \[\])/c\
    def cached_valves():\
        status = engine.get_cached_esp32_status()\
        return apply_inversion((status or {}).get("valves", []))' dashboard.py

# 3. Update fresh_valves body
sed -i '/def fresh_valves/,/return (status or {}).get("valves", \[\])/c\
    def fresh_valves():\
        """Fetch live valve state from ESP32 after a manual toggle."""\
        status = engine.get_esp32_status(force_fresh=True)\
        return apply_inversion((status or {}).get("valves", []))' dashboard.py

# 4. Swap action for inverted zones in api_valve handler
# Find the line "action = request.form..." and add inversion after it
sed -i '/action = request.form.get("action") or (payload or {}).get("action", "")/a\
        if zone_inverted(zone_id):\
            action = "close" if action == "open" else "open" if action == "close" else action' dashboard.py

echo "=== Verification ==="
grep -n 'zone_inverted\|apply_inversion\|inverted' dashboard.py
