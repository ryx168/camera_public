import os
import sys
import glob
import json
import re
import cv2
import numpy as np
import subprocess

with open("scratch_610pm_videos.json") as f:
    all_videos = json.load(f)

# Sort all videos chronologically
all_videos.sort(key=lambda x: x.get('epoch', 0))

# Filter between 4:00 PM and 7:00 PM on 2026-08-04
target_vids = []
for v in all_videos:
    pt = v.get('pacific_time', '')
    if '2026-08-04' in pt:
        h = v.get('hour', 0)
        if 16 <= h <= 18:
            target_vids.append(v)

print(f"Total VODs between 4:00 PM and 6:59 PM: {len(target_vids)}")

os.makedirs("driveway_entries", exist_ok=True)
os.makedirs("temp_vods", exist_ok=True)

# Download all target VODs
for v in target_vids:
    vid = v['id']
    pac_t = v['pacific_time']
    path = f"temp_vods/{vid}.mp4"
    if not os.path.exists(path):
        url = f"https://www.twitch.tv/videos/{vid.replace('v','')}"
        print(f"Downloading {vid} ({pac_t})...")
        subprocess.run([sys.executable, "-m", "yt_dlp", url, "-o", path, "--quiet"])

print("All VODs downloaded. Analyzing motion and vehicle entries in driveway & garage...")

entries = []

for v in target_vids:
    vid = v['id']
    pac_t = v['pacific_time']
    path = f"temp_vods/{vid}.mp4"
    if not os.path.exists(path): continue

    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    prev_k_gray = None
    max_k_motion = 0
    max_k_frame = None
    max_k_sec = 0
    
    for f_idx in range(0, frame_count, 3):
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
        ret, frame = cap.read()
        if not ret: break
        
        sec = f_idx / fps
        # Kitchen camera (top-right: driveway/garage area)
        k_crop = frame[0:240, 853:1280]
        # Specifically driveway region in kitchen view (y: 30 to 220, x: 0 to 350)
        k_driveway = k_crop[30:220, 0:350]
        k_gray = cv2.cvtColor(k_driveway, cv2.COLOR_BGR2GRAY)
        
        if prev_k_gray is not None:
            diff = cv2.absdiff(prev_k_gray, k_gray)
            _, thresh = cv2.threshold(diff, 20, 255, cv2.THRESH_BINARY)
            motion_area = int(np.sum(thresh > 0))
            
            if motion_area > max_k_motion:
                max_k_motion = motion_area
                max_k_frame = frame.copy()
                max_k_sec = sec
                
        prev_k_gray = k_gray
        
    cap.release()
    
    # If substantial driveway motion detected
    if max_k_motion > 5000:
        print(f"[DRIVEWAY MOTION] {vid} | {pac_t} (+{max_k_sec:.1f}s) | Motion Area: {max_k_motion}px")
        out_file = f"driveway_entries/{vid}_{pac_t.replace(':','').replace(' ','_')}_motion{max_k_motion}.jpg"
        cv2.putText(max_k_frame, f"DRIVEWAY ENTRY: {vid} | {pac_t} (+{max_k_sec:.1f}s) | Area: {max_k_motion}", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.imwrite(out_file, max_k_frame)
        entries.append({
            "vid": vid,
            "pacific_time": pac_t,
            "sec": max_k_sec,
            "motion": max_k_motion,
            "img": out_file
        })

with open("driveway_entries/entries.json", "w") as f:
    json.dump(entries, f, indent=2)

print(f"Driveway entry analysis complete! Found {len(entries)} events.")
