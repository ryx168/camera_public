import cv2
import numpy as np
import os
import sys

# Import functions from check_recent_motion
from check_recent_motion import detect_cameras_from_frame, get_camera_bounds, verify_moving_event, ALIAS_TO_CANONICAL

vids = [
    "v2837094777", # 09:08:34
    "v2837095266", # 09:09:19
    "v2837095825", # 09:10:07
    "v2837096289", # 09:10:48
    "v2837096673", # 09:11:26
    "v2837097078", # 09:12:03
    "v2837097490", # 09:12:40
]

os.makedirs("scratch_car_frames", exist_ok=True)

print("=== Analyzing downloaded videos for motion across ALL cameras ===")

for vid in vids:
    mp4_path = f"scratch_car_test/{vid}.mp4"
    if not os.path.exists(mp4_path):
        continue
    
    cap = cv2.VideoCapture(mp4_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 20
    frame_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_total / fps
    print(f"\n--- Analyzing {vid} (Duration: {duration:.1f}s, FPS: {fps}) ---")
    
    ret, first_frame = cap.read()
    if not ret:
        print("Could not read first frame.")
        cap.release()
        continue
        
    cam_map, cam_count, layout_name = detect_cameras_from_frame(first_frame)
    print(f"Detected layout: {layout_name} ({cam_count} cams). Detected map: {cam_map}")
    h, w = first_frame.shape[:2]
    print(f"Frame resolution: {w}x{h}")
    
    # Check all canonical cameras
    cameras_to_check = ['office', 'front', 'kitchen', 'balcony', 'backyard']
    
    # Save first frame of video for reference
    cv2.imwrite(f"scratch_car_frames/{vid}_first_frame.jpg", first_frame)
    
    # Reset cap
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    
    # Let's track motion in each camera across the entire video
    # We test multiple diff thresholds (e.g. 20, 25, 35) and record peak motion in each camera
    prev_cam_grays = {}
    peak_motions_per_cam = {cam: {'diff25': 0, 'diff35': 0, 'max_contour_area': 0, 'max_disp': 0, 'candidates': []} for cam in cameras_to_check}
    
    frame_idx = 0
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
        
        for cam_name in cameras_to_check:
            bounds = get_camera_bounds(frame, cam_name, camera_map=curr_map, cam_count=curr_count)
            if bounds is None: continue
            bx1, by1, bx2, by2 = bounds
            cam_crop = frame[by1:by2, bx1:bx2]
            if cam_crop.size == 0: continue
            
            gray = cv2.cvtColor(cam_crop, cv2.COLOR_BGR2GRAY)
            
            if cam_name in prev_cam_grays:
                prev_gray = prev_cam_grays[cam_name]
                if prev_gray.shape == gray.shape:
                    diff = cv2.absdiff(prev_gray, gray)
                    
                    _, th25 = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
                    _, th35 = cv2.threshold(diff, 35, 255, cv2.THRESH_BINARY)
                    
                    m25 = cv2.countNonZero(th25)
                    m35 = cv2.countNonZero(th35)
                    
                    if m25 > peak_motions_per_cam[cam_name]['diff25']:
                        peak_motions_per_cam[cam_name]['diff25'] = m25
                    if m35 > peak_motions_per_cam[cam_name]['diff35']:
                        peak_motions_per_cam[cam_name]['diff35'] = m35
                        
                    contours, _ = cv2.findContours(th25, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    if contours:
                        c_max = max(contours, key=cv2.contourArea)
                        c_area = cv2.contourArea(c_max)
                        if c_area > peak_motions_per_cam[cam_name]['max_contour_area']:
                            peak_motions_per_cam[cam_name]['max_contour_area'] = c_area
                            
                        if c_area > 300:
                            bx, by, bw, bh = cv2.boundingRect(c_max)
                            cx, cy = bx + bw/2.0, by + bh/2.0
                            peak_motions_per_cam[cam_name]['candidates'].append({
                                'time': t_sec,
                                'frame': frame.copy(),
                                'roi': bounds,
                                'bbox': (bx, by, bw, bh),
                                'center': (cx, cy),
                                'motion': m25,
                                'cam_count': curr_count,
                                'cam_slot': bounds,
                                'cam_name': cam_name
                            })
                            
                    # If noticeable motion, save a frame snapshot
                    if m25 > 2000:
                        cv2.imwrite(f"scratch_car_frames/{vid}_{cam_name}_t{t_sec:.1f}s_m{m25}.jpg", frame)
            
            prev_cam_grays[cam_name] = gray
            
    cap.release()
    
    print(f"Results for {vid}:")
    for cam, data in peak_motions_per_cam.items():
        cands = data['candidates']
        is_valid, three, move = verify_moving_event(cands, min_move_px=15.0) if len(cands) >= 3 else (False, None, 0.0)
        print(f"  Camera '{cam:8s}': Peak Motion (diff>35) = {data['diff35']:5d}px | (diff>25) = {data['diff25']:5d}px | Max Contour = {data['max_contour_area']:6.0f} | Candidates = {len(cands):3d} | Moving Verified: {is_valid} (Move: {move:.1f}px)")
