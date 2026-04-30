import json
d = json.load(open("/tmp/r.json"))
s = d["system"]
h = d["health"]
print("boot=%d uptime=%ds rssi=%d bat=%.2fV heap=%d crashCount=%d resetReason=%s" % (
    s["bootCount"], s["uptimeSec"], s["wifiRSSI"], s["batteryV"], s["freeHeap"],
    h["crashCount"], h["resetReasonName"]))
