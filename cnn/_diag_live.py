import json, urllib.request

ACER = "http://127.0.0.1:5125"
TOWER_CNN = "http://192.168.0.120:5201/cnn"
TOWER_RAW = "http://192.168.0.120:5200/raw.jpg"  # original color frame

# 1) grab the freshest raw frame the tower has (original color, pre-process)
def get(url, timeout=10, data=None, ctype=None):
    req = urllib.request.Request(url, data=data)
    if ctype:
        req.add_header("Content-Type", ctype)
    return urllib.request.urlopen(req, timeout=timeout).read()

try:
    raw = get(TOWER_RAW)
    print("raw frame bytes:", len(raw))
except Exception as e:
    print("raw fetch FAILED:", e)
    raw = None

# 2) CNN read of that frame
if raw:
    try:
        r = json.loads(get(TOWER_CNN, data=raw, ctype="image/jpeg").decode())
        print("CNN:", json.dumps({k: r.get(k) for k in
              ("digits", "value", "confidence", "min_conf", "per_digit_conf")}))
    except Exception as e:
        print("CNN read FAILED:", e)

# 3) oracle truth (uses the live vision_oracle on the Acer side via dashboard import)
import sys
sys.path.insert(0, "/home/jamesearlpace/smart-garden-server")
try:
    import vision_oracle, cam_ocr
    mr = None
    # current lock from state file
    import os
    sf = os.environ.get("METER_STATE_PATH", "/tmp/meter_state.json")
    if os.path.exists(sf):
        print("LOCK state:", open(sf).read().strip())
    if raw:
        res = vision_oracle.read_meter(raw, rotate180=True)
        print("ORACLE:", json.dumps(res))
except Exception as e:
    print("oracle/state FAILED:", e)
