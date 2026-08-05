import json

with open("car_610pm_results/instant_results.json") as f:
    results = json.load(f)

print(f"Total results: {len(results)}")

# Filter for Front and Kitchen cameras around 6:05 to 6:20 PM
front_kitchen = [r for r in results if r['cam'] in ['front', 'kitchen', 'office']]

print(f"\n--- Front / Kitchen / Office Events (sorted by time) ---")
for r in sorted(front_kitchen, key=lambda x: (x['pac_time'], x['cam'])):
    print(f"Time: {r['pac_time']} | Cam: {r['cam']:<7} | Area: {r['max_c_area']:>5.0f}px | Peak: +{r['peak_t']}s | VOD: {r['vid']} | URL: {r['video_url']}")
    for s in r['snapshots']:
        print(f"    - {s['phase'].upper()} (+{s['time']}s): {s['path']}")
