import cv2
import glob
import os
import numpy as np

files = sorted(glob.glob("extracted_910am/*.jpg"))
print(f"Total extracted frame files: {len(files)}")

from check_recent_motion import detect_cameras_from_frame, get_camera_bounds

vids_grouped = {}
for f in files:
    base = os.path.basename(f)
    parts = base.split('_')
    # e.g. 09_10_07_v2837095825_f01.jpg
    vid = parts[3]
    t_label = f"{parts[0]}:{parts[1]}:{parts[2]}"
    if vid not in vids_grouped:
        vids_grouped[vid] = (t_label, [])
    vids_grouped[vid][1].append(f)

cameras = ['office', 'front', 'kitchen', 'balcony', 'backyard']

for vid, (t_label, frame_paths) in vids_grouped.items():
    print(f"\n========================================================")
    print(f"VOD {vid} @ {t_label} (Total frames: {len(frame_paths)})")
    print(f"========================================================")
    
    first_img = cv2.imread(frame_paths[0])
    cam_map, cam_count, layout = detect_cameras_from_frame(first_img)
    print(f"Layout detected: {layout} ({cam_count} cams). Corner Map: {cam_map}")
    
    # Track per-camera motion across consecutive frames
    prev_crops = {}
    for cam in cameras:
        b = get_camera_bounds(first_img, cam, camera_map=cam_map, cam_count=cam_count)
        if b:
            bx1, by1, bx2, by2 = b
            prev_crops[cam] = cv2.cvtColor(first_img[by1:by2, bx1:bx2], cv2.COLOR_BGR2GRAY)
            
    for f_idx, fpath in enumerate(frame_paths[1:], start=2):
        img = cv2.imread(fpath)
        c_map, c_count, _ = detect_cameras_from_frame(img)
        
        for cam in cameras:
            b = get_camera_bounds(img, cam, camera_map=c_map, cam_count=c_count)
            if not b: continue
            bx1, by1, bx2, by2 = b
            crop_gray = cv2.cvtColor(img[by1:by2, bx1:bx2], cv2.COLOR_BGR2GRAY)
            
            if cam in prev_crops:
                p_gray = prev_crops[cam]
                if p_gray.shape == crop_gray.shape:
                    diff = cv2.absdiff(p_gray, crop_gray)
                    _, th15 = cv2.threshold(diff, 15, 255, cv2.THRESH_BINARY)
                    _, th25 = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
                    _, th35 = cv2.threshold(diff, 35, 255, cv2.THRESH_BINARY)
                    
                    m15 = cv2.countNonZero(th15)
                    m25 = cv2.countNonZero(th25)
                    m35 = cv2.countNonZero(th35)
                    
                    if m15 > 300: # print any notable motion
                        contours, _ = cv2.findContours(th25, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                        max_area = max([cv2.contourArea(c) for c in contours], default=0)
                        print(f"  Frame {f_idx:02d}s | Cam: {cam:8s} | Diff>15: {m15:5d}px | Diff>25: {m25:5d}px | Diff>35: {m35:5d}px | MaxContour: {max_area:5.0f}px")
                        
            prev_crops[cam] = crop_gray
