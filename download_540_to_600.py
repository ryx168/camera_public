import os
import sys
import subprocess
import json
import re

with open("scratch_610pm_videos.json") as f:
    all_videos = json.load(f)

# Download VODs between 5:45 PM and 6:00 PM
target_vids = []
for v in all_videos:
    pt = v.get('pacific_time', '')
    if '2026-08-04' in pt:
        m = re.search(r'05:(\d\d):', pt)
        if m and int(m.group(1)) >= 45:
            target_vids.append(v)

os.makedirs("temp_vods", exist_ok=True)

for v in target_vids:
    vid = v['id']
    pac_t = v['pacific_time']
    out_path = os.path.join("temp_vods", f"{vid}.mp4")
    if not os.path.exists(out_path):
        url = f"https://www.twitch.tv/videos/{vid.replace('v','')}"
        print(f"Downloading {vid} ({pac_t})...")
        subprocess.run([sys.executable, "-m", "yt_dlp", url, "-o", out_path, "--quiet"])

print("Downloaded target pre-6PM VODs!")
