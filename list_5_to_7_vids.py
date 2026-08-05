import os
import json
import re

with open("scratch_610pm_videos.json") as f:
    all_videos = json.load(f)

# Sort chronologically
all_videos.sort(key=lambda x: x.get('epoch', 0))

print(f"Total VODs: {len(all_videos)}")
print(f"Earliest VOD: {all_videos[0]['pacific_time']} (ID: {all_videos[0]['id']})")
print(f"Latest VOD: {all_videos[-1]['pacific_time']} (ID: {all_videos[-1]['id']})")

# Print all VODs between 5:00 PM and 7:00 PM
print("\n--- VODs between 5:00 PM and 7:00 PM ---")
for v in all_videos:
    pt = v.get('pacific_time', '')
    if '2026-08-04' in pt:
        h = v.get('hour', 0)
        m = v.get('minute', 0)
        if 17 <= h <= 18:
            print(f"{v['id']}: {pt} (duration: {v.get('duration', 0)}s)")
