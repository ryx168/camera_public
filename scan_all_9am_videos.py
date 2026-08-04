import os
import sys
import subprocess
import cv2
import numpy as np
import json
import datetime
from datetime import timezone

def get_pacific_time(dt=None, epoch=None):
    if epoch is not None:
        target_utc = datetime.datetime.fromtimestamp(epoch, tz=timezone.utc)
    elif dt is not None:
        if dt.tzinfo is None:
            target_utc = dt.replace(tzinfo=timezone.utc)
        else:
            target_utc = dt.astimezone(timezone.utc)
    else:
        target_utc = datetime.datetime.now(timezone.utc)
    tz_offset = datetime.timezone(datetime.timedelta(hours=-7), name="PDT")
    return target_utc.astimezone(tz_offset)

from check_recent_motion import detect_cameras_from_frame, get_camera_bounds

# List of VOD IDs between 08:55 AM and 09:25 AM
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

os.makedirs("scratch_all_9am", exist_ok=True)
os.makedirs("scratch_motion_found", exist_ok=True)

cameras_to_check = ['office', 'front', 'kitchen', 'balcony', 'backyard']

print(f"Starting scan of {len(vod_list)} videos around 9:10 AM PDT...")

motion_events = []

for vid, est_time in vod_list:
    url = f"https://www.twitch.tv/videos/{vid[1:]}"
    local_mp4 = f"scratch_all_9am/{vid}.mp4"
    
    if not os.path.exists(local_mp4) or os.path.getsize(local_mp4) < 10000:
        # download fast
        cmd = [sys.executable, "-m", "yt_dlp", "-f", "best", "-o", local_mp4, url]
        res = subprocess.run(cmd, capture_output=True, timeout=90)
        
    if not os.path.exists(local_mp4) or os.path.getsize(local_mp4) < 10000:
        print(f"Skipping {vid}: download failed.")
        continue
        
    cap = cv2.VideoCapture(local_mp4)
    fps = cap.get(cv2.CAP_PROP_FPS) or 20
    frame_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_total / fps
    
    ret, prev_frame = cap.read()
    if not ret:
        cap.release()
        continue
        
    init_map, init_count, init_layout = detect_cameras_from_frame(prev_frame)
    
    prev_cam_grays = {}
    for cam in cameras_to_check:
        b = get_camera_bounds(prev_frame, cam, camera_map=init_map, cam_count=init_count)
        if b:
            bx1, by1, bx2, by2 = b
            crop = prev_frame[by1:by2, bx1:bx2]
            if crop.size > 0:
                prev_cam_grays[cam] = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                
    frame_idx = 1
    skip = int(fps // 2)
    if skip < 1: skip = 1
    
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
            if cam in prev_cam_grays:
                p_gray = prev_cam_grays[cam]
                if p_gray.shape == gray.shape:
                    diff = cv2.absdiff(p_gray, gray)
                    # Use threshold 25
                    _, th = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
                    m = cv2.countNonZero(th)
                    
                    if m > 1500: # Significant motion
                        # Save frame
                        out_img = f"scratch_motion_found/{vid}_{cam}_t{t_sec:.1f}s_m{m}.jpg"
                        cv2.imwrite(out_img, frame)
                        motion_events.append({
                            'vid': vid,
                            'time_str': est_time,
                            't_sec': t_sec,
                            'cam': cam,
                            'motion': m,
                            'img': out_img
                        })
                        print(f"--> Motion in {vid} ({est_time}) on camera '{cam}' @ {t_sec:.1f}s: {m} pixels -> {out_img}")
            prev_cam_grays[cam] = gray
            
    cap.release()

print(f"\nTotal motion events found: {len(motion_events)}")
for ev in motion_events:
    print(f"VOD {ev['vid']} ({ev['time_str']}) | Cam: {ev['cam']} | t={ev['t_sec']:.1f}s | Motion: {ev['motion']}px")
