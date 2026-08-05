import json

with open("scratch_610pm_videos.json") as f:
    videos = json.load(f)

# Filter for Aug 4 between 5:50 PM and 6:30 PM
matches = []
for v in videos:
    pt = v.get('pacific_time', '')
    if '2026-08-04' in pt:
        # Check hour
        if ('05:' in pt and 'PM' in pt) or ('06:' in pt and 'PM' in pt):
            matches.append(v)

print(f"Total matches in 5 PM - 6 PM window: {len(matches)}")
for m in sorted(matches, key=lambda x: x['epoch']):
    print(f"{m['id']} | {m['pacific_time']} | Duration: {m.get('duration')}s | https://www.twitch.tv/videos/{m['id'].replace('v','')}")
