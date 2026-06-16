import json, urllib.request, os
recs = [json.loads(l) for l in open("/home/jamesearlpace/cnn-dataset-oracle/cnn_train.jsonl")]
print("dataset size:", len(recs))
ok = miss = 0
tested = 0
for rec in recs[:25]:
    f = rec["file"]
    if not os.path.isabs(f):
        for base in ("/home/jamesearlpace/meter-training", "/home/jamesearlpace/meter-training-quarantine"):
            cand = os.path.join(base, f)
            if os.path.exists(cand):
                f = cand; break
    if not os.path.exists(f):
        miss += 1
        continue
    data = open(f, "rb").read()
    req = urllib.request.Request("http://192.168.0.120:5201/cnn", data=data, headers={"Content-Type": "image/jpeg"})
    r = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
    tested += 1
    match = (r.get("digits") == rec["label"])
    if r.get("confidence") == "high":
        ok += 1
    print(f"{rec['label']} -> cnn={r.get('digits')} conf={r.get('confidence')} min={r.get('min_conf')} match={match}")
print(f"\ntested={tested} high_conf={ok} missing_files={miss}")
