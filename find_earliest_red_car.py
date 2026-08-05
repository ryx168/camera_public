import json

with open("kitchen_red_analysis/results.json") as f:
    results = json.load(f)

for r in results:
    print(f"{r['pacific_time']} | {r['vid']} | Red px: {r['red_pixels']}")
