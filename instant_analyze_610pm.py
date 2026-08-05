import os
import sys
import glob
import json
import re
import cv2
import numpy as np

with open("scratch_610pm_videos.json") as f:
    all_videos = json.load(f)

# Select all videos between 5:55 PM and 6:35 PM
target_vids = []
for v in all_videos:
    pt = v.get('pacific_time', '')
    if '2026-08-04' in pt:
        if ('05:5' in pt and 'PM' in pt) or ('06:' in pt and 'PM' in pt):
            m = re.search(r'06:(\d\d):', pt)
            if '05:5' in pt or (m and int(m.group(1)) <= 35):
                target_vids.append(v)

target_vids = sorted(target_vids, key=lambda x: x['epoch'])
print(f"Loaded {len(target_vids)} target videos from 5:55 PM to 6:35 PM.")

os.makedirs("car_610pm_results", exist_ok=True)

# Standard 5-cam geometry for 1280x480
# Cam 1 (office): [0:240, 0:426]
# Cam 2 (front):  [0:240, 426:853]
# Cam 3 (kitchen):[0:240, 853:1280]
# Cam 4 (balcony):[240:480, 0:640]
# Cam 5 (backyard):[240:480, 640:1280]

CAM_BOUNDS = {
    'office': (0, 0, 426, 240),
    'front': (426, 0, 853, 240),
    'kitchen': (853, 0, 1280, 240),
    'balcony': (0, 240, 640, 480),
    'backyard': (640, 240, 1280, 480)
}

results = []

for v_meta in target_vids:
    vid = v_meta['id']
    pac_time = v_meta['pacific_time']
    video_path = os.path.join("temp_vods", f"{vid}.mp4")
    
    if not os.path.exists(video_path):
        print(f"Skipping {vid}, not in temp_vods")
        continue
        
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    prev_grays = {}
    cam_data = {cam: {'max_c_area': 0, 'max_diff': 0, 'peak_t': 0, 'peak_box': None, 'peak_frame': None, 'frames_motion': 0, 'samples': []} for cam in CAM_BOUNDS}
    
    frame_idx = 0
    # Step every 2 frames for ultra fast & dense tracking
    step = 2
    
    while True:
        ret, frame = cap.read()
        if not ret: break
        frame_idx += 1
        
        if frame_idx % step != 0:
            continue
            
        t_sec = frame_idx / fps
        
        # Check each camera
        for cam, (x1, y1, x2, y2) in CAM_BOUNDS.items():
            crop = frame[y1:y2, x1:x2]
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (5, 5), 0)
            
            if cam in prev_grays:
                diff = cv2.absdiff(prev_grays[cam], gray)
                # threshold 22
                _, th = cv2.threshold(diff, 22, 255, cv2.THRESH_BINARY)
                motion_px = cv2.countNonZero(th)
                
                contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                max_c = 0
                best_box = None
                if contours:
                    c_largest = max(contours, key=cv2.contourArea)
                    max_c = cv2.contourArea(c_largest)
                    if max_c > 150:
                        best_box = cv2.boundingRect(c_largest)
                        
                cam_data[cam]['samples'].append((t_sec, motion_px, max_c, best_box, frame.copy()))
                
                if max_c > 600 or motion_px > 2500:
                    cam_data[cam]['frames_motion'] += 1
                    
                if max_c > cam_data[cam]['max_c_area']:
                    cam_data[cam]['max_c_area'] = max_c
                    cam_data[cam]['max_diff'] = motion_px
                    cam_data[cam]['peak_t'] = t_sec
                    cam_data[cam]['peak_box'] = best_box
                    cam_data[cam]['peak_frame'] = frame.copy()
                    
            prev_grays[cam] = gray
            
    cap.release()
    
    # Evaluate findings in this VOD
    for cam, st in cam_data.items():
        if st['max_c_area'] > 1200 or (cam in ['front', 'kitchen', 'office'] and st['max_c_area'] > 600):
            entry = {
                'vid': vid,
                'pac_time': pac_time,
                'cam': cam,
                'max_c_area': st['max_c_area'],
                'max_diff': st['max_diff'],
                'peak_t': st['peak_t'],
                'frames_motion': st['frames_motion'],
                'video_url': f"https://www.twitch.tv/videos/{vid.replace('v','')}",
                'snapshots': []
            }
            
            # Find peak index in samples
            samples = st['samples']
            peak_idx = -1
            for i, s in enumerate(samples):
                if abs(s[0] - st['peak_t']) < 0.1:
                    peak_idx = i
                    break
                    
            x1, y1, x2, y2 = CAM_BOUNDS[cam]
            start_idx = max(0, peak_idx - 5)
            end_idx = min(len(samples) - 1, peak_idx + 5)
            
            for phase_name, s_idx in [('start', start_idx), ('peak', peak_idx), ('end', end_idx)]:
                if 0 <= s_idx < len(samples):
                    t_val, d_val, c_val, box_val, f_img = samples[s_idx]
                    annotated = f_img.copy()
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    if box_val:
                        bx, by, bw, bh = box_val
                        cv2.rectangle(annotated, (x1 + bx, y1 + by), (x1 + bx + bw, y1 + by + bh), (0, 0, 255), 3)
                        
                    cv2.putText(annotated, f"CAMERA: {cam.upper()} | PHASE: {phase_name.upper()}", (x1 + 10, y1 + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                    cv2.putText(annotated, f"Time: {pac_time} (+{t_val:.1f}s)", (x1 + 10, y1 + 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
                    cv2.putText(annotated, f"Contour Area: {c_val:.0f}px", (x1 + 10, y1 + 90), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
                    
                    snap_name = f"car_610pm_results/snap_{cam}_{vid}_{phase_name}.jpg"
                    cv2.imwrite(snap_name, annotated)
                    
                    crop_name = f"car_610pm_results/crop_{cam}_{vid}_{phase_name}.jpg"
                    cv2.imwrite(crop_name, annotated[y1:y2, x1:x2])
                    
                    entry['snapshots'].append({
                        'phase': phase_name,
                        'time': f"{t_val:.1f}",
                        'path': snap_name,
                        'crop_path': crop_name
                    })
                    
            results.append(entry)
            print(f"--> DETECTED: {pac_time} | VOD {vid} | Cam: {cam} | Area: {st['max_c_area']:.0f}px | Peak: +{st['peak_t']:.1f}s")

print(f"\n=======================================================")
print(f"Total detections: {len(results)}")
with open("car_610pm_results/instant_results.json", "w") as f:
    json.dump(results, f, indent=2)
