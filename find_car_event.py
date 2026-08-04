import os
import sys
import subprocess
import cv2
import numpy as np
import json
import datetime
from datetime import timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

from check_recent_motion import prepare_local_vod, detect_cameras_from_frame, get_camera_bounds, get_pacific_time

vod_list = [
    ("v2837084455", "08:55:43 AM"),
    ("v2837084992", "08:56:29 AM"),
    ("v2837085483", "08:57:12 AM"),
    ("v2837086030", "08:57:57 AM"),
    ("v2837086602", "08:58:42 AM"),
    ("v2837087203", "08:59:26 AM"),
    ("v2837088124", "09:00:12 AM"),
    ("v2837088987", "09:00:58 AM"),
    ("v2837089755", "09:01:45 AM"),
    ("v2837090372", "09:02:33 AM"),
    ("v2837091037", "09:03:25 AM"),
    ("v2837091668", "09:04:17 AM"),
    ("v2837092298", "09:05:10 AM"),
    ("v2837092898", "09:06:01 AM"),
    ("v2837093580", "09:06:53 AM"),
    ("v2837094198", "09:07:43 AM"),
    ("v2837094777", "09:08:34 AM"),
    ("v2837095266", "09:09:19 AM"),
    ("v2837095825", "09:10:07 AM"),
    ("v2837096289", "09:10:48 AM"),
    ("v2837096673", "09:11:26 AM"),
    ("v2837097078", "09:12:03 AM"),
    ("v2837097490", "09:12:40 AM"),
    ("v2837097916", "09:13:18 AM"),
    ("v2837098373", "09:13:56 AM"),
    ("v2837098878", "09:14:35 AM"),
    ("v2837099351", "09:15:15 AM"),
    ("v2837099827", "09:15:56 AM"),
    ("v2837100234", "09:16:34 AM"),
    ("v2837100681", "09:17:15 AM"),
    ("v2837101125", "09:17:55 AM"),
    ("v2837101570", "09:18:37 AM"),
    ("v2837102050", "09:19:19 AM"),
    ("v2837102539", "09:20:04 AM"),
    ("v2837103040", "09:20:49 AM"),
    ("v2837103524", "09:21:33 AM"),
    ("v2837104048", "09:22:19 AM"),
    ("v2837104543", "09:23:02 AM"),
    ("v2837104988", "09:23:44 AM"),
    ("v2837105437", "09:24:25 AM"),
]

vids = [v[0] for v in vod_list]
time_map = {v[0]: v[1] for v in vod_list}

print(f"1. Downloading {len(vids)} VODs in parallel...")
vod_sources = {}
with ThreadPoolExecutor(max_workers=8) as executor:
    futures = {executor.submit(prepare_local_vod, vid, "temp_vods"): vid for vid in vids}
    for future in as_completed(futures):
        vid, url, path = future.result()
        if path:
            vod_sources[vid] = path
            print(f"  Ready: {vid} -> {path}")
        else:
            print(f"  FAILED: {vid}")

print(f"\n2. Analyzing {len(vod_sources)} ready VODs...")
os.makedirs("car_motion_snapshots", exist_ok=True)

cameras_to_check = ['office', 'front', 'kitchen', 'balcony', 'backyard']

all_detections = []

for vid in vids:
    if vid not in vod_sources: continue
    path = vod_sources[vid]
    est_time = time_map[vid]
    
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 20
    
    ret, prev_frame = cap.read()
    if not ret:
        cap.release()
        continue
        
    init_map, init_count, _ = detect_cameras_from_frame(prev_frame)
    
    prev_grays = {}
    for cam in cameras_to_check:
        b = get_camera_bounds(prev_frame, cam, camera_map=init_map, cam_count=init_count)
        if b:
            bx1, by1, bx2, by2 = b
            crop = prev_frame[by1:by2, bx1:bx2]
            if crop.size > 0:
                prev_grays[cam] = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                
    frame_idx = 1
    skip = int(fps // 2)
    if skip < 1: skip = 1
    
    vid_cam_peak = {cam: {'peak_m': 0, 'peak_area': 0, 'peak_t': 0, 'samples': []} for cam in cameras_to_check}
    
    while True:
        for _ in range(skip - 1):
            cap.read()
            frame_idx += 1
            
        ret, frame = cap.read()
        if not ret: break
        frame_idx += 1
        t_sec = frame_idx / fps
        
        curr_map, curr_count, _ = detect_cameras_from_frame(frame)
        
        for cam in cameras_to_check:
            b = get_camera_bounds(frame, cam, camera_map=curr_map, cam_count=curr_count)
            if not b: continue
            bx1, by1, bx2, by2 = b
            crop = frame[by1:by2, bx1:bx2]
            if crop.size == 0: continue
            
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            if cam in prev_grays:
                p_gray = prev_grays[cam]
                if p_gray.shape == gray.shape:
                    diff = cv2.absdiff(p_gray, gray)
                    # test threshold 20 & 30
                    _, th20 = cv2.threshold(diff, 20, 255, cv2.THRESH_BINARY)
                    _, th30 = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
                    m20 = cv2.countNonZero(th20)
                    m30 = cv2.countNonZero(th30)
                    
                    contours, _ = cv2.findContours(th20, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    max_c_area = 0
                    c_box = None
                    if contours:
                        c_max = max(contours, key=cv2.contourArea)
                        max_c_area = cv2.contourArea(c_max)
                        if max_c_area > 150:
                            c_box = cv2.boundingRect(c_max)
                            
                    if m20 > vid_cam_peak[cam]['peak_m']:
                        vid_cam_peak[cam]['peak_m'] = m20
                        vid_cam_peak[cam]['peak_area'] = max_c_area
                        vid_cam_peak[cam]['peak_t'] = t_sec
                        
                    if m20 > 500: # Any noticeable motion
                        vid_cam_peak[cam]['samples'].append((t_sec, m20, m30, max_c_area, frame.copy(), b, c_box))
                        
            prev_grays[cam] = gray
            
    cap.release()
    
    # Check if any camera had significant motion
    for cam, data in vid_cam_peak.items():
        if data['peak_m'] > 600:
            print(f"[{est_time}] VOD {vid} - Cam '{cam:8s}': Peak Motion = {data['peak_m']}px (at t={data['peak_t']:.1f}s, Max Contour = {data['peak_area']:.0f}px)")
            # Save snapshots of top 3 motion frames
            sorted_samples = sorted(data['samples'], key=lambda x: x[1], reverse=True)
            for idx, (s_t, s_m20, s_m30, s_area, s_frame, s_bounds, s_cbox) in enumerate(sorted_samples[:3]):
                out_path = f"car_motion_snapshots/{est_time.replace(':', '_').replace(' ', '_')}_{vid}_{cam}_t{s_t:.1f}s_m{s_m20}.jpg"
                if s_bounds:
                    bx1, by1, bx2, by2 = s_bounds
                    cv2.rectangle(s_frame, (bx1, by1), (bx2, by2), (0, 255, 255), 2)
                    if s_cbox:
                        cx, cy, cw, ch = s_cbox
                        cv2.rectangle(s_frame, (bx1+cx, by1+cy), (bx1+cx+cw, by1+cy+ch), (0, 0, 255), 2)
                cv2.imwrite(out_path, s_frame)
                all_detections.append({
                    'vid': vid,
                    'time_str': est_time,
                    'cam': cam,
                    't_sec': s_t,
                    'm20': s_m20,
                    'm30': s_m30,
                    'area': s_area,
                    'file': out_path
                })

print(f"\nAnalysis complete. Total motion frames recorded: {len(all_detections)}")
