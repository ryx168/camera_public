import os
import json
import re

with open("scratch_610pm_videos.json") as f:
    all_videos = json.load(f)

print(f"Total videos in metadata: {len(all_videos)}")

# Group by hour on 2026-08-04
hour_buckets = {}
for v in all_videos:
    pt = v.get('pacific_time', '')
    if '2026-08-04' in pt:
        h = v.get('hour', 0)
        hour_buckets.setdefault(h, []).append(v)

for h in sorted(hour_buckets.keys()):
    v_list = hour_buckets[h]
    print(f"Hour {h:02d}:00 - {len(v_list)} VODs (First: {v_list[0]['pacific_time']}, Last: {v_list[-1]['pacific_time']})")
