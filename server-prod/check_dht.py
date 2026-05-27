import json, sys
from datetime import datetime

data = json.load(sys.stdin)
print(f"Total rows: {len(data)}")
if data:
    print(f"First: {data[0]['ts']}")
    print(f"Last:  {data[-1]['ts']}")
    
    prev = None
    gaps = []
    for r in data:
        dt = datetime.fromisoformat(r['ts'])
        if prev and (dt - prev).total_seconds() > 600:
            gaps.append((prev, dt, round((dt - prev).total_seconds() / 60)))
        prev = dt
    
    print(f"\nGaps > 10 min: {len(gaps)}")
    for g in gaps:
        print(f"  {g[0]} -> {g[1]}  ({g[2]} min)")
    
    # Check for nulls
    nulls = sum(1 for r in data if r.get('temp_f') is None)
    print(f"\nNull temp_f rows: {nulls} / {len(data)}")
