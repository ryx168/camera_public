import os
import sys
import glob
import json
import re
import cv2
import numpy as np

# Let's inspect all VODs from 6:05 PM to 6:18 PM
with open("scratch_610pm_videos.json") as f:
    all_videos = json.load(f)

vids_map = {v['id']: v for v in all_videos}

target_ids = [
    "v2837523729", # 06:05:11 PM
    "v2837524781", # 06:06:13 PM
    "v2837525711", # 06:07:08 PM
    "v2837526606", # 06:08:06 PM
    "v2837527477", # 06:09:05 PM
    "v2837528327", # 06:10:07 PM  <-- EXACT 6:10 PM!
    "v2837529137", # 06:11:06 PM  <-- EXACT 6:11 PM!
    "v2837529844", # 06:11:57 PM  <-- EXACT 6:12 PM!
    "v2837530574", # 06:12:45 PM
    "v2837531341", # 06:13:34 PM
    "v2837532048", # 06:14:23 PM
    "v2837532825", # 06:15:18 PM
    "v2837533670", # 06:16:14 PM
    "v2837534496", # 06:17:11 PM
    "v2837535220", # 06:18:08 PM
]

os.makedirs("car_exact_610", exist_ok=True)

# CAM_BOUNDS:
# front: (426, 0, 853, 240)
# kitchen: (853, 0, 1280, 240)
# office: (0, 0, 426, 240)

for vid in target_ids:
    meta = vids_map.get(vid, {})
    pac_t = meta.get('pacific_time', 'Unknown Time')
    path = os.path.join("temp_vods", f"{vid}.mp4")
    if not os.path.exists(path):
        print(f"File {path} does not exist")
        continue
        
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps
    
    print(f"\n==========================================")
    print(f"Analyzing VOD {vid} | {pac_t} | Duration: {duration:.1f}s ({frame_count} frames)")
    
    prev_front_gray = None
    prev_kitchen_gray = None
    
    max_front_motion = 0
    max_kitchen_motion = 0
    peak_front_t = 0
    peak_kitchen_t = 0
    
    front_frames = []
    kitchen_frames = []
    
    f_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret: break
        f_idx += 1
        
        # Sample every frame for precise detection
        t_sec = f_idx / fps
        
        # Front crop:
        front_crop = frame[0:240, 426:853]
        # Street / driveway part of front: top 130 pixels
        front_driveway = front_crop[0:130, :]
        
        # Kitchen crop:
        kitchen_crop = frame[0:240, 853:1280]
        
        f_gray = cv2.cvtColor(front_driveway, cv2.COLOR_BGR2GRAY)
        k_gray = cv2.cvtColor(kitchen_crop, cv2.COLOR_BGR2GRAY)
        
        if prev_front_gray is not None:
            f_diff = cv2.absdiff(prev_front_gray, f_gray)
            _, f_th = cv2.threshold(f_diff, 20, 255, cv2.THRESH_BINARY)
            f_cnt = cv2.countNonZero(f_th)
            
            f_contours, _ = cv2.findContours(f_th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            f_max_c = max([cv2.contourArea(c) for c in f_contours], default=0)
            
            if f_max_c > max_front_motion:
                max_front_motion = f_max_c
                peak_front_t = t_sec
                
            if f_max_c > 200 or f_cnt > 800:
                front_frames.append((t_sec, f_max_c, f_cnt, frame.copy()))
                
        if prev_kitchen_gray is not None:
            k_diff = cv2.absdiff(prev_kitchen_gray, k_gray)
            _, k_th = cv2.threshold(k_diff, 20, 255, cv2.THRESH_BINARY)
            k_cnt = cv2.countNonZero(k_th)
            
            k_contours, _ = cv2.findContours(k_th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            k_max_c = max([cv2.contourArea(c) for c in k_contours], default=0)
            
            if k_max_c > max_kitchen_motion:
                max_kitchen_motion = k_max_c
                peak_kitchen_t = t_sec
                
            if k_max_c > 200 or k_cnt > 800:
                kitchen_frames.append((t_sec, k_max_c, k_cnt, frame.copy()))
                
        prev_front_gray = f_gray
        prev_kitchen_gray = k_gray
        
    cap.release()
    
    print(f"  Front Street Peak Motion: Area={max_front_motion:.0f} at {peak_front_t:.1f}s (Motion frames: {len(front_frames)})")
    print(f"  Kitchen / Driveway Peak:  Area={max_kitchen_motion:.0f} at {peak_kitchen_t:.1f}s (Motion frames: {len(kitchen_frames)})")
    
    # If any notable motion, save sequence of frames
    if len(front_frames) > 0:
        # Sort and save top 3 key frames
        front_frames.sort(key=lambda x: x[1], reverse=True)
        for i, (t_val, c_val, cnt_val, frm) in enumerate(front_frames[:4]):
            # Annotate
            ann = frm.copy()
            cv2.rectangle(ann, (426, 0), (853, 240), (0, 255, 0), 2)
            cv2.putText(ann, f"FRONT CAM MOTION - {pac_t} (+{t_val:.1f}s)", (436, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            cv2.putText(ann, f"Motion Area: {c_val:.0f}px", (436, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
            cv2.imwrite(f"car_exact_610/front_{vid}_rank{i}_{t_val:.1f}s.jpg", ann)
            cv2.imwrite(f"car_exact_610/front_crop_{vid}_rank{i}_{t_val:.1f}s.jpg", ann[0:240, 426:853])
            
    if len(kitchen_frames) > 0:
        kitchen_frames.sort(key=lambda x: x[1], reverse=True)
        for i, (t_val, c_val, cnt_val, frm) in enumerate(kitchen_frames[:4]):
            ann = frm.copy()
            cv2.rectangle(ann, (853, 0), (1280, 240), (0, 255, 0), 2)
            cv2.putText(ann, f"KITCHEN CAM MOTION - {pac_t} (+{t_val:.1f}s)", (863, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            cv2.putText(ann, f"Motion Area: {c_val:.0f}px", (863, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
            cv2.imwrite(f"car_exact_610/kitchen_{vid}_rank{i}_{t_val:.1f}s.jpg", ann)
            cv2.imwrite(f"car_exact_610/kitchen_crop_{vid}_rank{i}_{t_val:.1f}s.jpg", ann[0:240, 853:1280])

print("\nExact 6:10 PM analysis completed!")
