import os
import sys
import glob
import json
import re
import cv2
import numpy as np

with open("scratch_610pm_videos.json") as f:
    all_videos = json.load(f)

# Filter 5:50 PM to 6:35 PM
target_vids = []
for v in all_videos:
    pt = v.get('pacific_time', '')
    if '2026-08-04' in pt:
        if ('05:5' in pt and 'PM' in pt) or ('06:' in pt and 'PM' in pt):
            m = re.search(r'06:(\d\d):', pt)
            if '05:5' in pt or (m and int(m.group(1)) <= 35):
                target_vids.append(v)

target_vids = sorted(target_vids, key=lambda x: x['epoch'])

os.makedirs("car_detailed_snapshots", exist_ok=True)

events = []

for v in target_vids:
    vid = v['id']
    pac_t = v['pacific_time']
    path = os.path.join("temp_vods", f"{vid}.mp4")
    if not os.path.exists(path):
        continue
        
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps
    
    prev_front = None
    prev_kitchen = None
    
    front_max = 0
    kitchen_max = 0
    front_peak_t = 0
    kitchen_peak_t = 0
    front_peak_frame = None
    kitchen_peak_frame = None
    
    front_samples = []
    kitchen_samples = []
    
    f_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret: break
        f_idx += 1
        
        t_sec = f_idx / fps
        
        # Front cam
        front_crop = frame[0:240, 426:853]
        f_gray = cv2.cvtColor(front_crop, cv2.COLOR_BGR2GRAY)
        
        # Kitchen cam
        kitchen_crop = frame[0:240, 853:1280]
        k_gray = cv2.cvtColor(kitchen_crop, cv2.COLOR_BGR2GRAY)
        
        if prev_front is not None:
            f_diff = cv2.absdiff(prev_front, f_gray)
            _, f_th = cv2.threshold(f_diff, 22, 255, cv2.THRESH_BINARY)
            f_cnt = cv2.countNonZero(f_th)
            f_contours, _ = cv2.findContours(f_th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            f_c = max([cv2.contourArea(c) for c in f_contours], default=0)
            
            if f_c > front_max:
                front_max = f_c
                front_peak_t = t_sec
                front_peak_frame = frame.copy()
            if f_c > 300:
                front_samples.append((t_sec, f_c, frame.copy()))
                
        if prev_kitchen is not None:
            k_diff = cv2.absdiff(prev_kitchen, k_gray)
            _, k_th = cv2.threshold(k_diff, 22, 255, cv2.THRESH_BINARY)
            k_cnt = cv2.countNonZero(k_th)
            k_contours, _ = cv2.findContours(k_th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            k_c = max([cv2.contourArea(c) for c in k_contours], default=0)
            
            if k_c > kitchen_max:
                kitchen_max = k_c
                kitchen_peak_t = t_sec
                kitchen_peak_frame = frame.copy()
            if k_c > 300:
                kitchen_samples.append((t_sec, k_c, frame.copy()))
                
        prev_front = f_gray
        prev_kitchen = k_gray
        
    cap.release()
    
    if front_max > 500 or kitchen_max > 500 or len(front_samples) > 2 or len(kitchen_samples) > 2:
        print(f"VOD {vid} ({pac_t}): Front Max Area={front_max:.0f} (peak +{front_peak_t:.1f}s, {len(front_samples)} motion frames) | Kitchen Max Area={kitchen_max:.0f} (peak +{kitchen_peak_t:.1f}s, {len(kitchen_samples)} motion frames)")
        
        events.append({
            'vid': vid,
            'pac_time': pac_t,
            'front_max': front_max,
            'front_peak_t': front_peak_t,
            'kitchen_max': kitchen_max,
            'kitchen_peak_t': kitchen_peak_t,
            'front_samples_count': len(front_samples),
            'kitchen_samples_count': len(kitchen_samples),
            'video_url': f"https://www.twitch.tv/videos/{vid.replace('v','')}"
        })
        
        # Save snapshot of front peak
        if front_peak_frame is not None and front_max > 400:
            ann_f = front_peak_frame.copy()
            cv2.rectangle(ann_f, (426, 0), (853, 240), (0, 255, 0), 2)
            cv2.putText(ann_f, f"FRONT CAM ACTIVITY - {pac_t} (+{front_peak_t:.1f}s)", (436, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2)
            cv2.putText(ann_f, f"Motion Area: {front_max:.0f}px", (436, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
            cv2.imwrite(f"car_detailed_snapshots/peak_front_{vid}_{front_max:.0f}.jpg", ann_f)
            cv2.imwrite(f"car_detailed_snapshots/crop_front_{vid}_{front_max:.0f}.jpg", ann_f[0:240, 426:853])
            
        # Save snapshot of kitchen peak
        if kitchen_peak_frame is not None and kitchen_max > 400:
            ann_k = kitchen_peak_frame.copy()
            cv2.rectangle(ann_k, (853, 0), (1280, 240), (0, 255, 0), 2)
            cv2.putText(ann_k, f"KITCHEN/DRIVEWAY ACTIVITY - {pac_t} (+{kitchen_peak_t:.1f}s)", (863, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2)
            cv2.putText(ann_k, f"Motion Area: {kitchen_max:.0f}px", (863, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
            cv2.imwrite(f"car_detailed_snapshots/peak_kitchen_{vid}_{kitchen_max:.0f}.jpg", ann_k)
            cv2.imwrite(f"car_detailed_snapshots/crop_kitchen_{vid}_{kitchen_max:.0f}.jpg", ann_k[0:240, 853:1280])

with open("car_detailed_snapshots/summary.json", "w") as f:
    json.dump(events, f, indent=2)

print("\nFull scan complete!")
