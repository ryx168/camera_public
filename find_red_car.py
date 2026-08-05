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

# Filter all videos between 5:30 PM and 6:45 PM
target_vids = []
for v in all_videos:
    pt = v.get('pacific_time', '')
    if '2026-08-04' in pt:
        m = re.search(r'(\d\d):(\d\d):', pt)
        if m:
            h = int(m.group(1))
            minute = int(m.group(2))
            # 5:30 PM (17:30) to 6:45 PM (18:45)
            # note pt is in 12h format e.g. "05:45:08 PM PDT" or "06:10:07 PM PDT"
            is_pm = 'PM' in pt
            if is_pm:
                if h == 5 and minute >= 30:
                    target_vids.append(v)
                elif h == 6 and minute <= 45:
                    target_vids.append(v)

# Sort chronologically
target_vids.sort(key=lambda x: x.get('epoch', 0))

print(f"Total target VODs to search for red car: {len(target_vids)}")

os.makedirs("temp_vods", exist_ok=True)
os.makedirs("red_car_search", exist_ok=True)

# 1. Ensure all target VODs are downloaded
for v in target_vids:
    vid = v['id']
    pac_t = v['pacific_time']
    path = f"temp_vods/{vid}.mp4"
    if not os.path.exists(path):
        url = f"https://www.twitch.tv/videos/{vid.replace('v','')}"
        print(f"Downloading {vid} ({pac_t})...")
        subprocess.run([sys.executable, "-m", "yt_dlp", url, "-o", path, "--quiet"])

print("All VODs ready. Scanning for red car entering garage...")

results = []

for v in target_vids:
    vid = v['id']
    pac_t = v['pacific_time']
    path = f"temp_vods/{vid}.mp4"
    if not os.path.exists(path): continue

    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # Check every 5th frame (~0.25s interval)
    prev_kitchen_gray = None
    prev_front_gray = None
    
    max_red_kitchen = 0
    max_red_front = 0
    best_red_frame = None
    best_sec = 0
    
    # Also track motion
    max_motion_kitchen = 0
    
    for f_idx in range(0, frame_count, 4):
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
        ret, frame = cap.read()
        if not ret: break
        
        sec = f_idx / fps
        
        # Crops
        # Kitchen (top-right, [0:240, 853:1280]) - Driveway & Garage entrance
        kitchen = frame[0:240, 853:1280]
        # Front (top-mid, [0:240, 426:853])
        front = frame[0:240, 426:853]
        
        # Convert to HSV to detect RED color
        hsv_k = cv2.cvtColor(kitchen, cv2.COLOR_BGR2HSV)
        hsv_f = cv2.cvtColor(front, cv2.COLOR_BGR2HSV)
        
        # Red in HSV wraps around 0 and 180
        lower_red1 = np.array([0, 70, 50])
        upper_red1 = np.array([10, 255, 255])
        lower_red2 = np.array([165, 70, 50])
        upper_red2 = np.array([180, 255, 255])
        
        mask_k1 = cv2.inRange(hsv_k, lower_red1, upper_red1)
        mask_k2 = cv2.inRange(hsv_k, lower_red2, upper_red2)
        mask_k = mask_k1 | mask_k2
        
        mask_f1 = cv2.inRange(hsv_f, lower_red1, upper_red1)
        mask_f2 = cv2.inRange(hsv_f, lower_red2, upper_red2)
        mask_f = mask_f1 | mask_f2
        
        # Exclude the red flower pot at bottom of stairs in Front camera if needed,
        # but let's count red pixels in driveway area of Kitchen (top half of kitchen is driveway / street)
        # Driveway area in kitchen: y: 0 to 200, x: 0 to 400
        red_k_count = int(np.sum(mask_k > 0))
        red_f_count = int(np.sum(mask_f > 0))
        
        # Motion in kitchen
        gray_k = cv2.cvtColor(kitchen, cv2.COLOR_BGR2GRAY)
        if prev_kitchen_gray is not None:
            diff_k = cv2.absdiff(prev_kitchen_gray, gray_k)
            _, thresh_k = cv2.threshold(diff_k, 25, 255, cv2.THRESH_BINARY)
            motion_k = int(np.sum(thresh_k > 0))
            if motion_k > max_motion_kitchen:
                max_motion_kitchen = motion_k
        prev_kitchen_gray = gray_k
        
        if red_k_count > max_red_kitchen:
            max_red_kitchen = red_k_count
            best_red_frame = frame.copy()
            best_sec = sec
            
    cap.release()
    
    print(f"VOD {vid} ({pac_t}): Max Kitchen Red={max_red_kitchen}px | Max Kitchen Motion={max_motion_kitchen}px")
    
    # If high red or high motion in kitchen driveway, save snapshot
    if best_red_frame is not None:
        cv2.putText(best_red_frame, f"{vid} | {pac_t} (+{best_sec:.1f}s) Red={max_red_kitchen}", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.imwrite(f"red_car_search/{vid}_{pac_t.replace(':','').replace(' ','_')}_peak.jpg", best_red_frame)
        
    results.append({
        "id": vid,
        "pacific_time": pac_t,
        "max_red_kitchen": max_red_kitchen,
        "max_motion_kitchen": max_motion_kitchen,
        "peak_sec": best_sec
    })

with open("red_car_search/results.json", "w") as f:
    json.dump(results, f, indent=2)

print("Red car search complete!")
