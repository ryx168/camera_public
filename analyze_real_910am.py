import cv2
import glob
import os
import numpy as np
from check_recent_motion import detect_cameras_from_frame, get_camera_bounds

files = sorted(glob.glob("real_910am_frames/*.jpg"))
print(f"Total extracted frames: {len(files)}")

os.makedirs("detected_car_motion", exist_ok=True)

vids_grouped = {}
for f in files:
    base = os.path.basename(f)
    parts = base.split('_')
    vid = parts[3]
    t_label = f"{parts[0]}:{parts[1]}:{parts[2]}"
    if vid not in vids_grouped:
        vids_grouped[vid] = (t_label, [])
    vids_grouped[vid][1].append(f)

cameras = ['office', 'front', 'kitchen', 'balcony', 'backyard']

for vid, (t_label, frame_paths) in vids_grouped.items():
    first_img = cv2.imread(frame_paths[0])
    cam_map, cam_count, layout = detect_cameras_from_frame(first_img)
    
    prev_crops = {}
    for cam in cameras:
        b = get_camera_bounds(first_img, cam, camera_map=cam_map, cam_count=cam_count)
        if b:
            bx1, by1, bx2, by2 = b
            prev_crops[cam] = cv2.cvtColor(first_img[by1:by2, bx1:bx2], cv2.COLOR_BGR2GRAY)
            
    print(f"\n--- Video {vid} (Camera Time approx {t_label}) ---")
    for f_idx, fpath in enumerate(frame_paths[1:], start=2):
        img = cv2.imread(fpath)
        c_map, c_count, _ = detect_cameras_from_frame(img)
        
        for cam in cameras:
            b = get_camera_bounds(img, cam, camera_map=c_map, cam_count=c_count)
            if not b: continue
            bx1, by1, bx2, by2 = b
            crop = img[by1:by2, bx1:bx2]
            crop_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            
            if cam in prev_crops:
                p_gray = prev_crops[cam]
                if p_gray.shape == crop_gray.shape:
                    diff = cv2.absdiff(p_gray, crop_gray)
                    _, th20 = cv2.threshold(diff, 20, 255, cv2.THRESH_BINARY)
                    _, th30 = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
                    m20 = cv2.countNonZero(th20)
                    m30 = cv2.countNonZero(th30)
                    
                    contours, _ = cv2.findContours(th20, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    max_c = max([cv2.contourArea(c) for c in contours], default=0)
                    
                    if m20 > 500 or max_c > 300:
                        print(f"  Frame {f_idx:02d} | Cam: {cam:8s} | Diff>20: {m20:5d}px | Diff>30: {m30:5d}px | MaxContour: {max_c:5.0f}px")
                        # Save frame
                        c_max_obj = max(contours, key=cv2.contourArea) if contours else None
                        out_img = img.copy()
                        cv2.rectangle(out_img, (bx1, by1), (bx2, by2), (0, 255, 255), 2)
                        if c_max_obj is not None and max_c > 100:
                            cx, cy, cw, ch = cv2.boundingRect(c_max_obj)
                            cv2.rectangle(out_img, (bx1+cx, by1+cy), (bx1+cx+cw, by1+cy+ch), (0, 0, 255), 2)
                        out_path = f"detected_car_motion/{t_label.replace(':', '_')}_{vid}_{cam}_f{f_idx:02d}_m{m20}.jpg"
                        cv2.imwrite(out_path, out_img)
                        
            prev_crops[cam] = crop_gray
