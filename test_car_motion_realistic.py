import cv2
import glob
import os
import numpy as np

files = sorted(glob.glob("extracted_910am/*_f*.jpg"))

from check_recent_motion import detect_cameras_from_frame, get_camera_bounds

vids_grouped = {}
for f in files:
    base = os.path.basename(f)
    if "crop" in base: continue
    parts = base.split('_')
    vid = parts[3]
    t_label = f"{parts[0]}:{parts[1]}:{parts[2]}"
    if vid not in vids_grouped:
        vids_grouped[vid] = (t_label, [])
    vids_grouped[vid][1].append(f)

print("Testing motion on Front camera (driveway/porch) with realistic parameters:")
print("DIFF_THRESHOLD = 25, MOTION_THRESHOLD = 600, MIN_CONTOUR_AREA = 200\n")

for vid, (t_label, frame_paths) in vids_grouped.items():
    first_img = cv2.imread(frame_paths[0])
    cam_map, cam_count, layout = detect_cameras_from_frame(first_img)
    
    b_front = get_camera_bounds(first_img, 'front', camera_map=cam_map, cam_count=cam_count)
    if not b_front: continue
    
    bx1, by1, bx2, by2 = b_front
    cw = bx2 - bx1
    ch = by2 - by1
    
    # ROI: full width, bottom 80% (ROI_Y_MIN = 0.20)
    roi_front = first_img[by1 + int(ch*0.2): by2, bx1: bx2]
    prev_gray = cv2.cvtColor(roi_front, cv2.COLOR_BGR2GRAY)
    
    events = []
    for f_idx, fpath in enumerate(frame_paths[1:], start=2):
        img = cv2.imread(fpath)
        c_map, c_count, _ = detect_cameras_from_frame(img)
        b = get_camera_bounds(img, 'front', camera_map=c_map, cam_count=c_count)
        if not b: continue
        bx1, by1, bx2, by2 = b
        roi = img[by1 + int(ch*0.2): by2, bx1: bx2]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        
        diff = cv2.absdiff(prev_gray, gray)
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        motion = cv2.countNonZero(thresh)
        
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        max_c = max([cv2.contourArea(c) for c in contours], default=0)
        
        if motion > 600 or max_c > 200:
            events.append((f_idx, motion, max_c))
            
        prev_gray = gray
        
    print(f"[{t_label}] VOD {vid}: {len(events)} candidate motion frames (Max Motion: {max([e[1] for e in events], default=0)} px, Max Contour: {max([e[2] for e in events], default=0)} px)")
