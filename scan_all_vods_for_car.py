import os
import sys
import glob
import json
import re
import cv2
import numpy as np
import subprocess
from concurrent.futures import ThreadPoolExecutor

with open("scratch_610pm_videos.json") as f:
    all_videos = json.load(f)

# Sort chronologically
all_videos.sort(key=lambda x: x.get('epoch', 0))

# All videos on 2026-08-04
target_vids = [v for v in all_videos if '2026-08-04' in v.get('pacific_time', '')]

print(f"Total videos to check: {len(target_vids)}")

os.makedirs("temp_vods", exist_ok=True)
os.makedirs("car_entry_events", exist_ok=True)

def download_vod(v):
    vid = v['id']
    path = f"temp_vods/{vid}.mp4"
    if not os.path.exists(path) or os.path.getsize(path) < 1000:
        url = f"https://www.twitch.tv/videos/{vid.replace('v','')}"
        subprocess.run([sys.executable, "-m", "yt_dlp", url, "-o", path, "--quiet"])
    return vid

# Download missing in parallel
print("Downloading missing VODs with ThreadPoolExecutor...")
with ThreadPoolExecutor(max_workers=5) as executor:
    list(executor.map(download_vod, target_vids))

print("All VODs downloaded! Now scanning for car entering garage / driveway...")

detected_events = []

for v in target_vids:
    vid = v['id']
    pac_t = v['pacific_time']
    path = f"temp_vods/{vid}.mp4"
    if not os.path.exists(path): continue

    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    prev_k_gray = None
    prev_f_gray = None
    
    for f_idx in range(0, frame_count, 3):
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
        ret, frame = cap.read()
        if not ret: break
        
        sec = f_idx / fps
        
        # Kitchen (driveway/garage area): [0:240, 853:1280]
        kitchen = frame[0:240, 853:1280]
        # Front (street/stairs/driveway edge): [0:240, 426:853]
        front = frame[0:240, 426:853]
        
        # Driveway area in kitchen
        k_drive = kitchen[20:220, 0:380]
        k_gray = cv2.cvtColor(k_drive, cv2.COLOR_BGR2GRAY)
        
        # Check for RED pixels in driveway or front street
        hsv_k = cv2.cvtColor(k_drive, cv2.COLOR_BGR2HSV)
        hsv_f = cv2.cvtColor(front, cv2.COLOR_BGR2HSV)
        
        # Red HSV ranges
        mask_r1 = cv2.inRange(hsv_k, np.array([0, 80, 50]), np.array([10, 255, 255]))
        mask_r2 = cv2.inRange(hsv_k, np.array([170, 80, 50]), np.array([180, 255, 255]))
        red_k = int(np.sum((mask_r1 | mask_r2) > 0))
        
        mask_f_r1 = cv2.inRange(hsv_f[:150, :], np.array([0, 80, 50]), np.array([10, 255, 255]))
        mask_f_r2 = cv2.inRange(hsv_f[:150, :], np.array([170, 80, 50]), np.array([180, 255, 255]))
        red_f = int(np.sum((mask_f_r1 | mask_f_r2) > 0))
        
        # Motion in driveway
        motion_k = 0
        if prev_k_gray is not None:
            diff = cv2.absdiff(prev_k_gray, k_gray)
            _, th = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
            motion_k = int(np.sum(th > 0))
            
        prev_k_gray = k_gray
        
        # If significant red or significant driveway motion
        if red_k > 150 or red_f > 200 or motion_k > 2000:
            print(f"EVENT: {vid} | {pac_t} (+{sec:.1f}s) | RedK: {red_k}px, RedF: {red_f}px, MotionK: {motion_k}px")
            out_img = f"car_entry_events/{vid}_t{sec:.1f}s_rK{red_k}_rF{red_f}_mK{motion_k}.jpg"
            cv2.putText(frame, f"{pac_t} (+{sec:.1f}s) rK:{red_k} rF:{red_f} mK:{motion_k}", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            cv2.imwrite(out_img, frame)
            detected_events.append({
                "vid": vid,
                "pacific_time": pac_t,
                "sec": sec,
                "red_k": red_k,
                "red_f": red_f,
                "motion_k": motion_k,
                "img": out_img
            })
            
    cap.release()

with open("car_entry_events/events.json", "w") as f:
    json.dump(detected_events, f, indent=2)

print(f"Done! Detected {len(detected_events)} events across all VODs.")
