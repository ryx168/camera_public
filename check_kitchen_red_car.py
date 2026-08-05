import cv2
import glob
import os
import json
import numpy as np

os.makedirs("kitchen_red_analysis", exist_ok=True)

with open("scratch_610pm_videos.json") as f:
    all_videos = json.load(f)

all_videos.sort(key=lambda x: x.get('epoch', 0))

results = []

for v in all_videos:
    vid = v['id']
    pt = v['pacific_time']
    path = f"temp_vods/{vid}.mp4"
    if not os.path.exists(path): continue
    
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # Check middle frame of each video
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_count / 2))
    ret, frame = cap.read()
    if not ret: 
        cap.release()
        continue
    
    # Kitchen camera: [0:240, 853:1280]
    kitchen = frame[0:240, 853:1280]
    
    # Lower left area of kitchen: [150:240, 0:120]
    corner = kitchen[150:240, 0:120]
    
    # Red mask in HSV
    hsv = cv2.cvtColor(corner, cv2.COLOR_BGR2HSV)
    mask1 = cv2.inRange(hsv, np.array([0, 70, 50]), np.array([10, 255, 255]))
    mask2 = cv2.inRange(hsv, np.array([170, 70, 50]), np.array([180, 255, 255]))
    red_mask = mask1 | mask2
    red_pixels = int(cv2.countNonZero(red_mask))
    
    results.append({
        "vid": vid,
        "pacific_time": pt,
        "red_pixels": red_pixels
    })
    
    cap.release()

with open("kitchen_red_analysis/results.json", "w") as f:
    json.dump(results, f, indent=2)

print(f"Analyzed {len(results)} videos for red car in Kitchen Cam 3!")
for r in results:
    if "06:0" in r['pacific_time'] or "06:1" in r['pacific_time'] or "06:2" in r['pacific_time']:
        print(f"{r['pacific_time']} | {r['vid']} | Red px: {r['red_pixels']}")
