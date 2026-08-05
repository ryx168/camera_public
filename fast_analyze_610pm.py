import os
import sys
import cv2
import numpy as np
import json
import glob
import re
from check_recent_motion import detect_cameras_from_frame, get_camera_bounds, get_pacific_time

with open("scratch_610pm_videos.json") as f:
    all_videos = json.load(f)

# Filter 6:00 PM to 6:30 PM (and also 5:50 - 6:00 just in case)
target_vids = []
for v in all_videos:
    pt = v.get('pacific_time', '')
    if '2026-08-04' in pt:
        if ('05:5' in pt and 'PM' in pt) or ('06:' in pt and 'PM' in pt):
            m = re.search(r'06:(\d\d):', pt)
            if '05:5' in pt or (m and int(m.group(1)) <= 35):
                target_vids.append(v)

target_vids = sorted(target_vids, key=lambda x: x['epoch'])
print(f"Targeting {len(target_vids)} VODs around 5:50 PM - 6:35 PM PDT")

os.makedirs("car_610pm_results", exist_ok=True)
cameras_to_check = ['front', 'kitchen', 'office', 'balcony', 'backyard']

events = []

for v_meta in target_vids:
    vid = v_meta['id']
    pac_time = v_meta['pacific_time']
    path = os.path.join("temp_vods", f"{vid}.mp4")
    if not os.path.exists(path):
        continue
        
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    ret, first_frame = cap.read()
    if not ret:
        cap.release()
        continue
        
    cam_map, cam_count, layout = detect_cameras_from_frame(first_frame)
    
    # Pre-calculate bounds for each camera
    bounds_map = {}
    for cam in cameras_to_check:
        b = get_camera_bounds(first_frame, cam, camera_map=cam_map, cam_count=cam_count)
        if b:
            bounds_map[cam] = b
            
    # Sample every 3 frames (~6-7 fps)
    step = 3
    prev_grays = {}
    
    # Tracking max motion
    cam_results = {cam: {'max_c_area': 0, 'max_diff_px': 0, 'peak_t': 0, 'peak_box': None, 'peak_frame': None, 'frames_with_motion': 0, 'history': []} for cam in bounds_map}
    
    frame_idx = 0
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    
    while True:
        ret, frame = cap.read()
        if not ret: break
        frame_idx += 1
        
        if frame_idx % step != 0:
            continue
            
        t_sec = frame_idx / fps
        
        for cam, b in bounds_map.items():
            bx1, by1, bx2, by2 = b
            crop = frame[by1:by2, bx1:bx2]
            if crop.size == 0: continue
            
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (5, 5), 0)
            
            if cam in prev_grays:
                p_gray = prev_grays[cam]
                if p_gray.shape == gray.shape:
                    diff = cv2.absdiff(p_gray, gray)
                    _, th25 = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
                    diff_px = cv2.countNonZero(th25)
                    
                    contours, _ = cv2.findContours(th25, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    max_c = 0
                    best_box = None
                    if contours:
                        c_largest = max(contours, key=cv2.contourArea)
                        max_c = cv2.contourArea(c_largest)
                        if max_c > 200:
                            best_box = cv2.boundingRect(c_largest)
                            
                    cam_results[cam]['history'].append((t_sec, diff_px, max_c, best_box, frame.copy()))
                    
                    if max_c > 500 or diff_px > 2000:
                        cam_results[cam]['frames_with_motion'] += 1
                        
                    if max_c > cam_results[cam]['max_c_area']:
                        cam_results[cam]['max_c_area'] = max_c
                        cam_results[cam]['max_diff_px'] = diff_px
                        cam_results[cam]['peak_t'] = t_sec
                        cam_results[cam]['peak_box'] = best_box
                        cam_results[cam]['peak_frame'] = frame.copy()
                        
            prev_grays[cam] = gray
            
    cap.release()
    
    # Check for notable events in this VOD
    for cam, res in cam_results.items():
        if res['max_c_area'] > 1200 or res['max_diff_px'] > 8000 or res['frames_with_motion'] >= 3:
            event_obj = {
                'vid': vid,
                'pac_time': pac_time,
                'cam': cam,
                'max_c_area': res['max_c_area'],
                'max_diff_px': res['max_diff_px'],
                'peak_t': res['peak_t'],
                'frames_with_motion': res['frames_with_motion'],
                'bounds': bounds_map[cam],
                'video_url': f"https://www.twitch.tv/videos/{vid.replace('v','')}"
            }
            events.append(event_obj)
            
            # Save START, PEAK, END snapshots
            hist = res['history']
            peak_idx = -1
            for i, h in enumerate(hist):
                if abs(h[0] - res['peak_t']) < 0.1:
                    peak_idx = i
                    break
                    
            start_idx = max(0, peak_idx - 6)
            end_idx = min(len(hist) - 1, peak_idx + 6)
            
            bx1, by1, bx2, by2 = bounds_map[cam]
            
            for phase_name, f_idx in [('start', start_idx), ('peak', peak_idx), ('end', end_idx)]:
                if f_idx >= 0 and f_idx < len(hist):
                    t_val, d_val, c_val, box_val, f_img = hist[f_idx]
                    annotated = f_img.copy()
                    cv2.rectangle(annotated, (bx1, by1), (bx2, by2), (0, 255, 0), 2)
                    if box_val:
                        cx, cy, cw, ch = box_val
                        cv2.rectangle(annotated, (bx1 + cx, by1 + cy), (bx1 + cx + cw, by1 + cy + ch), (0, 0, 255), 3)
                    
                    cv2.putText(annotated, f"CAMERA: {cam.upper()} | PHASE: {phase_name.upper()}", (bx1 + 10, by1 + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                    cv2.putText(annotated, f"Time: {pac_time} (+{t_val:.1f}s)", (bx1 + 10, by1 + 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
                    cv2.putText(annotated, f"Motion Area: {c_val:.0f}px | Pixels: {d_val}", (bx1 + 10, by1 + 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                    
                    out_path = f"car_610pm_results/snapshot_{cam}_{vid}_{phase_name}.jpg"
                    cv2.imwrite(out_path, annotated)
                    
                    # Also save cropped camera view
                    cam_crop_annotated = annotated[by1:by2, bx1:bx2]
                    cv2.imwrite(f"car_610pm_results/crop_{cam}_{vid}_{phase_name}.jpg", cam_crop_annotated)
                    
            print(f"--> EVENT DETECTED: {pac_time} | VOD {vid} | Cam '{cam}' | Peak at {res['peak_t']:.1f}s | Area: {res['max_c_area']:.0f}px | Frames: {res['frames_with_motion']}")

print(f"\n==================================================")
print(f"Total events detected: {len(events)}")
with open("car_610pm_results/detected_events.json", "w") as f:
    # Serialize clean events without numpy objects
    clean_events = []
    for e in events:
        c_e = dict(e)
        c_e['bounds'] = list(c_e['bounds'])
        clean_events.append(c_e)
    json.dump(clean_events, f, indent=2)

for e in sorted(events, key=lambda x: x['max_c_area'], reverse=True):
    print(f"  {e['pac_time']} | Cam: {e['cam']} | VOD: {e['vid']} | Area: {e['max_c_area']:.0f}px | URL: {e['video_url']} at {e['peak_t']:.1f}s")
