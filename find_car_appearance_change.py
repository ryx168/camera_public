import json
import os
import cv2
import numpy as np
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from check_recent_motion import prepare_local_vod, detect_cameras_from_frame, get_camera_bounds

with open("videos.json", "r") as f:
    data = json.load(f)

# Find all videos between 8:30 AM and 10:00 AM on 2026-08-04
videos = []
for v in data:
    created_at = v.get("created_at")
    vid = f"v{v.get('id')}"
    # Parse UTC time
    dt = datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    # PDT is UTC-7
    pdt = dt.astimezone(datetime.timezone(datetime.timedelta(hours=-7)))
    if pdt.hour == 8 and pdt.minute >= 30 or pdt.hour == 9 or (pdt.hour == 10 and pdt.minute <= 30):
        videos.append((vid, pdt.strftime("%I:%M:%S %p"), pdt))

videos.sort(key=lambda x: x[2])
print(f"Found {len(videos)} videos between 08:30 AM and 10:30 AM.")

# We will sample 1 frame from each video and crop the car region
os.makedirs("car_timeline", exist_ok=True)

def process_vid(v_info):
    vid, t_str, _ = v_info
    v, u, path = prepare_local_vod(vid, "temp_vods")
    if not path or not os.path.exists(path):
        return None
    cap = cv2.VideoCapture(path)
    ret, frame = cap.read()
    cap.release()
    if not ret: return None
    
    c_map, c_count, _ = detect_cameras_from_frame(frame)
    b = get_camera_bounds(frame, 'front', camera_map=c_map, cam_count=c_count)
    if not b: return None
    bx1, by1, bx2, by2 = b
    front = frame[by1:by2, bx1:bx2]
    
    # Save the front camera image
    out_front = f"car_timeline/{t_str.replace(':', '_').replace(' ', '_')}_{vid}.jpg"
    cv2.imwrite(out_front, front)
    
    # Crop the car/driveway zone on right side
    h, w = front.shape[:2]
    car_crop = front[int(h*0.35):h, int(w*0.75):w]
    
    # Average color / brightness of car zone
    avg_val = np.mean(car_crop)
    
    return vid, t_str, out_front, avg_val

import datetime

results = []
with ThreadPoolExecutor(max_workers=8) as executor:
    futures = [executor.submit(process_vid, v) for v in videos]
    for fut in as_completed(futures):
        res = fut.result()
        if res:
            results.append(res)

results.sort(key=lambda x: x[1])
print("\nTimeline of car region brightness across 08:30 AM - 10:30 AM:")
for vid, t_str, out_front, avg_val in results:
    print(f"[{t_str}] {vid}: Car Region Mean Brightness = {avg_val:.2f}")
