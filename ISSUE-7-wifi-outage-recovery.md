# ESP32 unreachable after ISP switchover — IP conflict with Samsung TV

**Severity:** HIGH (resolved)  
**Date:** 2026-05-05  
**Status:** RESOLVED — root cause was IP conflict, not lwIP wedge  
**Related:** Misdiagnosed as #5 (lwIP wedge) for ~2 hours before real RCA

## Summary

After switching ISP from Ziply Fiber to Comcast (Saturday May 3), the ESP32 Smart Garden controller appeared to suffer constant web server wedges — port 80 alternating between 200 OK and Connection Refused every few seconds. After extended misdiagnosis as the known lwIP wedge bug (#5), the actual root cause was an **IP conflict**: the Samsung Frame 55" TV (`1c:af:4a:10:69:e4`) grabbed `192.168.0.150` via DHCP during the outage, colliding with the ESP32's static IP assignment in firmware.

## Root Cause

1. Saturday May 3: Internet cut for ISP switchover. All devices lost connectivity.
2. When power/network restored, the ER605 DHCP server assigned `192.168.0.150` to the Samsung Frame TV (which requests IPs via DHCP).
3. The ESP32 boots with `192.168.0.150` hardcoded as a static IP in firmware (`config.h`).
4. Two devices on the same IP = ARP responses alternate between the TV's MAC and the ESP32's MAC.
5. When the server's ARP cache pointed to the TV → "Connection refused" (no web server on port 80).
6. When the ARP cache pointed to the ESP32 → clean HTTP 200.
7. This created the appearance of the #5 lwIP wedge bug (intermittent RSTs), but with a completely different cause.

## Evidence

ARP probe test (before fix) showed alternating MACs:
```
probe 1: 1c:af:4a:10:69:e4  (Samsung TV)
probe 2: 1c:af:4a:10:69:e4  (Samsung TV)
probe 3: 1c:af:4a:10:69:e4  (Samsung TV)
probe 4: 1c:af:4a:10:69:e4  (Samsung TV)
probe 5: 68:fe:71:0c:ba:98  (ESP32)     ← only 1 in 5 reached the real device
```

After fix — 10/10 probes resolve to ESP32, 99 minutes uptime with zero failures:
```
probe 1-10: 68:fe:71:0c:ba:98  (ESP32)
MAC=68:FE:71:0C:BA:98 Battery=12.92V Uptime=5961s RSSI=-58
```

## Fix Applied

1. **DHCP reservation** on ER605: MAC `68:FE:71:0C:BA:98` → `192.168.0.150` (prevents any other device from getting this IP)
2. **Samsung TV power cycled** — released its .150 lease, got a new IP via DHCP
3. Result: ESP32 stable, 99+ minutes uptime, zero Connection Refused errors

## Other Fixes Made During This Session

1. **Xfinity gateway set to bridge mode** — disabled its WiFi (CJWII) and NAT to prevent devices from bypassing home-net-watch monitoring
2. **irrigation.py patched** — health/sensor data logging now runs before the `installed_zones` check, so voltage/temp/RSSI are logged even with no zones installed
3. **smart-garden-server config** temporarily changed to .118 (wrong device) then reverted to .150

## Diagnostic Mistakes Made (for future reference)

1. **Assumed #5 lwIP wedge without checking ARP.** The SYN→RST symptom was identical to #5, but the cause was different. Should have run `arp -n | grep 150` immediately — would have seen the Samsung TV MAC and diagnosed the conflict in 30 seconds.
2. **Confused two ESP32 devices.** MAC `dc:da:0c:2c:3f:6c` (nicknamed "IoT Device (ESP32)" in nicknames.json) is NOT the Smart Garden ESP32 (`68:FE:71:0C:BA:98`). Changed server config to the wrong IP (.118) based on this confusion.
3. **Created a duplicate issue file** with wrong diagnosis, then had to rewrite twice.
4. **Spent ~2 hours on lwIP investigation** (firmware source analysis, pcap, tcpdump) before checking the most basic network diagnostic (ARP table).

## Lessons

1. **When ESP32 is "intermittently unreachable" after a network change, check for IP conflicts FIRST.** Run: `arp -d 192.168.0.150; ping -c 1 192.168.0.150; arp -n | grep 150` — if the MAC isn't `68:FE:71:0C:BA:98`, you have a conflict.
2. **Static IPs need DHCP reservations.** The firmware uses a static IP, but the DHCP server doesn't know about it. Without a reservation, DHCP can hand that IP to another device.
3. **Always verify the MAC before diagnosing the application.** Network-layer problems masquerade as app-layer bugs.
