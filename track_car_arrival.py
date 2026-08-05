import os
import sys
import glob
import json
import re
import cv2
import numpy as np

# Load all videos from 5:00 PM to 6:30 PM
with open("scratch_610pm_videos.json") as f:
    all_videos = json.load(f)

# Sort all videos chronologically
all_videos.sort(key=lambda x: x['epoch'])

os.makedirs("car_arrival_tracking", exist_ok=True)

# We want to inspect every single VOD from 5:30 PM to 6:20 PM
target_vids = []
for v in all_videos:
    pt = v.get('pacific_time', '')
    if '2026-08-04' in pt:
        # Check hour
        m = re.search(r'(\d\d):(\d\d):(\d\d) (AM|PM)', pt)
        if m:
            hr = int(m.group(1))
            minute = int(m.group(2))
            ampm = m.group(4)
            if ampm == 'PM':
                if hr == 5 and minute >= 30:
                    target_vids.append(v)
                elif hr == 6 and minute <= 30:
                    target_vids.append(v)

print(f"Tracking car across {len(target_vids)} VODs from 5:30 PM to 6:30 PM...")

summary_timeline = []

for v in target_vids:
    vid = v['id']
    pac_t = v['pacific_time']
    path = os.path.join("temp_vods", f"{vid}.mp4")
    
    # If not downloaded, download it
    if not os.path.exists(path):
        url = f"https://www.twitch.tv/videos/{vid.replace('v','')}"
        print(f"Downloading {vid} ({pac_t})...")
        os.system(f'yt-dlp "{url}" -o "{path}" --quiet')
        
    if not os.path.exists(path):
        continue
        
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # Grab middle frame
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_count // 2)
    ret, mid_frame = cap.read()
    cap.release()
    
    if ret:
        # Save a montage of Front (top middle) and Kitchen (top right)
        front_crop = mid_frame[0:240, 426:853]
        kitchen_crop = mid_frame[0:240, 853:1280]
        
        # Combine side by side
        combined = np.hstack([front_crop, kitchen_crop])
        cv2.putText(combined, f"{vid} | {pac_t}", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        
        out_name = f"car_arrival_tracking/timeline_{vid}.jpg"
        cv2.imwrite(out_name, combined)
        
        summary_timeline.append({
            'vid': vid,
            'pac_time': pac_t,
            'file': out_name,
            'epoch': v['epoch']
        })

with open("car_arrival_tracking/timeline.json", "w") as f:
    json.dump(summary_timeline, f, indent=2)

print("Timeline extraction complete!")
