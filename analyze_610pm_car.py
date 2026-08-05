import os
import sys
import cv2
import numpy as np
import json
import re
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from check_recent_motion import prepare_local_vod, detect_cameras_from_frame, get_camera_bounds, get_pacific_time

# Target videos from 6:00 PM to 6:25 PM PDT
with open("scratch_610pm_videos.json") as f:
    all_videos = json.load(f)

# Filter 6:00 PM to 6:25 PM
target_vids = []
for v in all_videos:
    pt = v.get('pacific_time', '')
    if '2026-08-04' in pt and '06:' in pt and 'PM' in pt:
        # Check minute
        m = re.search(r'06:(\d\d):', pt)
        if m:
            minute = int(m.group(1))
            if 0 <= minute <= 25:
                target_vids.append(v)

target_vids = sorted(target_vids, key=lambda x: x['epoch'])
print(f"Targeting {len(target_vids)} VODs around 6:00 - 6:25 PM:")
for v in target_vids:
    print(f"  {v['id']} ({v['pacific_time']}) - duration {v.get('duration')}s")

# 1. Download / Prepare VODs in parallel
os.makedirs("temp_vods", exist_ok=True)
os.makedirs("car_610pm_results", exist_ok=True)

vod_sources = {}
vids = [v['id'] for v in target_vids]

print("\nDownloading VODs...")
with ThreadPoolExecutor(max_workers=8) as executor:
    futures = {executor.submit(prepare_local_vod, vid, "temp_vods"): vid for vid in vids}
    for future in as_completed(futures):
        vid, url, path = future.result()
        if path and os.path.exists(path):
            vod_sources[vid] = path
            print(f"  Ready: {vid} -> {path}")
        else:
            print(f"  FAILED: {vid}")

print(f"\nDownloaded {len(vod_sources)} VODs. Now performing deep motion and car detection analysis across all cameras...")

cameras_to_check = ['office', 'front', 'kitchen', 'balcony', 'backyard']
analysis_results = []

for v_meta in target_vids:
    vid = v_meta['id']
    if vid not in vod_sources: continue
    path = vod_sources[vid]
    pac_time = v_meta['pacific_time']
    
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 20
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    ret, first_frame = cap.read()
    if not ret:
        cap.release()
        continue
        
    init_map, init_count, layout_name = detect_cameras_from_frame(first_frame)
    
    # Save a reference frame
    cv2.imwrite(f"car_610pm_results/ref_{vid}.jpg", first_frame)
    
    # Analyze frame by frame (sampling at 5 fps)
    step = max(1, int(fps // 5))
    prev_crops = {}
    
    # Track peak motion per camera
    cam_stats = {cam: {'max_motion': 0, 'max_contour_area': 0, 'peak_frame': None, 'peak_t': 0, 'best_box': None, 'motion_frames': 0} for cam in cameras_to_check}
    
    frame_idx = 0
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    
    all_frames_data = []
    
    while True:
        ret, frame = cap.read()
        if not ret: break
        frame_idx += 1
        
        if frame_idx % step != 0:
            continue
            
        t_sec = frame_idx / fps
        curr_map, curr_count, _ = detect_cameras_from_frame(frame)
        
        frame_cam_motion = {}
        
        for cam in cameras_to_check:
            b = get_camera_bounds(frame, cam, camera_map=curr_map, cam_count=curr_count)
            if not b: 
                # Try fallback layout
                b = get_camera_bounds(frame, cam, camera_map=init_map, cam_count=init_count)
            if not b: continue
            
            bx1, by1, bx2, by2 = b
            crop = frame[by1:by2, bx1:bx2]
            if crop.size == 0: continue
            
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (5, 5), 0)
            
            if cam in prev_crops:
                prev_gray = prev_crops[cam]
                if prev_gray.shape == gray.shape:
                    diff = cv2.absdiff(prev_gray, gray)
                    _, th = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
                    motion_px = cv2.countNonZero(th)
                    
                    contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    max_c_area = 0
                    best_c_box = None
                    if contours:
                        c_max = max(contours, key=cv2.contourArea)
                        max_c_area = cv2.contourArea(c_max)
                        if max_c_area > 300:
                            best_c_box = cv2.boundingRect(c_max)
                    
                    if motion_px > 500:
                        cam_stats[cam]['motion_frames'] += 1
                        
                    if max_c_area > cam_stats[cam]['max_contour_area'] or motion_px > cam_stats[cam]['max_motion']:
                        if max_c_area > cam_stats[cam]['max_contour_area']:
                            cam_stats[cam]['max_contour_area'] = max_c_area
                            cam_stats[cam]['best_box'] = best_c_box
                        if motion_px > cam_stats[cam]['max_motion']:
                            cam_stats[cam]['max_motion'] = motion_px
                        cam_stats[cam]['peak_frame'] = frame.copy()
                        cam_stats[cam]['peak_crop'] = crop.copy()
                        cam_stats[cam]['peak_t'] = t_sec
                        cam_stats[cam]['bounds'] = b
                        
            prev_crops[cam] = gray
            
    cap.release()
    
    # Summarize this VOD
    vod_summary = {
        'vid': vid,
        'pacific_time': pac_time,
        'cam_stats': {}
    }
    for cam, st in cam_stats.items():
        vod_summary['cam_stats'][cam] = {
            'max_motion': st['max_motion'],
            'max_contour_area': st['max_contour_area'],
            'motion_frames': st['motion_frames'],
            'peak_t': st['peak_t'],
            'has_peak_frame': st['peak_frame'] is not None
        }
        if st['max_contour_area'] > 1000 or st['max_motion'] > 8000:
            print(f"  [SIGNIFICANT MOTION] VOD {vid} ({pac_time}) | Cam '{cam}': max_c_area={st['max_contour_area']}, motion_px={st['max_motion']} at {st['peak_t']:.1f}s")
            
            # Save annotated snapshot
            annotated = st['peak_frame'].copy()
            bx1, by1, bx2, by2 = st['bounds']
            cv2.rectangle(annotated, (bx1, by1), (bx2, by2), (0, 255, 0), 2)
            if st['best_box']:
                cx, cy, cw, ch = st['best_box']
                cv2.rectangle(annotated, (bx1 + cx, by1 + cy), (bx1 + cx + cw, by1 + cy + ch), (0, 0, 255), 3)
                cv2.putText(annotated, f"{cam.upper()} MOTION (Area: {st['max_contour_area']:.0f})", (bx1 + 10, by1 + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                cv2.putText(annotated, f"Time: {pac_time} (+{st['peak_t']:.1f}s)", (bx1 + 10, by1 + 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
                
            out_name = f"car_610pm_results/motion_{vid}_{cam}_{st['max_contour_area']:.0f}.jpg"
            cv2.imwrite(out_name, annotated)
            st['snapshot_path'] = out_name
            
    analysis_results.append((v_meta, cam_stats))

with open("car_610pm_results/summary.json", "w") as f:
    json_export = []
    for vm, cs in analysis_results:
        cs_clean = {}
        for c, st in cs.items():
            cs_clean[c] = {
                'max_motion': st['max_motion'],
                'max_contour_area': st['max_contour_area'],
                'motion_frames': st['motion_frames'],
                'peak_t': st['peak_t'],
                'snapshot_path': st.get('snapshot_path')
            }
        json_export.append({'vid': vm['id'], 'time': vm['pacific_time'], 'stats': cs_clean})
    json.dump(json_export, f, indent=2)

print("\nAnalysis complete! Inspecting findings...")
