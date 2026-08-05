import cv2
import os
import glob
import json
import numpy as np

# Load video metadata
with open("scratch_610pm_videos.json") as f:
    all_videos = json.load(f)

vids_map = {v['id']: v for v in all_videos}

os.makedirs("red_car_detections", exist_ok=True)

# Scan all mp4 files in temp_vods
mp4_files = glob.glob("temp_vods/*.mp4")
print(f"Scanning {len(mp4_files)} downloaded VODs for RED CAR across all 5 cameras...")

findings = []

for mp4 in mp4_files:
    vid = os.path.splitext(os.path.basename(mp4))[0]
    meta = vids_map.get(vid, {})
    pac_t = meta.get('pacific_time', 'Unknown Time')
    
    cap = cv2.VideoCapture(mp4)
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # Check every 4th frame
    for f_idx in range(0, frame_count, 4):
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
        ret, frame = cap.read()
        if not ret: break
        
        sec = f_idx / fps
        
        # 5 camera regions
        cams = {
            "office": frame[0:240, 0:426],
            "front": frame[0:240, 426:853],
            "kitchen": frame[0:240, 853:1280],
            "balcony": frame[240:480, 0:499],
            "backyard": frame[240:480, 499:1280]
        }
        
        for cam_name, cam_img in cams.items():
            # Check for red in HSV
            hsv = cv2.cvtColor(cam_img, cv2.COLOR_BGR2HSV)
            
            # Bright / saturated red
            lower_red1 = np.array([0, 100, 70])
            upper_red1 = np.array([10, 255, 255])
            lower_red2 = np.array([170, 100, 70])
            upper_red2 = np.array([180, 255, 255])
            
            m1 = cv2.inRange(hsv, lower_red1, upper_red1)
            m2 = cv2.inRange(hsv, lower_red2, upper_red2)
            mask = m1 | m2
            
            # If camera is front, ignore bottom stairs red flower pot (y > 150)
            if cam_name == "front":
                mask[150:, :] = 0
            # If camera is office, ignore bottom planters (y > 180)
            if cam_name == "office":
                mask[180:, :] = 0
            # If camera is balcony, ignore red pots on ground (y > 180, x < 150)
            if cam_name == "balcony":
                mask[160:, :200] = 0
            # If camera is backyard, ignore red pots in shelf (x < 150, y < 150)
            if cam_name == "backyard":
                mask[:180, :150] = 0
                
            red_pixels = int(np.sum(mask > 0))
            
            if red_pixels > 250:  # Significant red object (car, vehicle, etc.)
                print(f"--> RED OBJECT in {cam_name.upper()}: {vid} ({pac_t} +{sec:.1f}s) - {red_pixels} red px")
                out_name = f"red_car_detections/{vid}_{cam_name}_t{sec:.1f}s_red{red_pixels}.jpg"
                cv2.putText(frame, f"RED DETECTED in {cam_name}: {pac_t} (+{sec:.1f}s)", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                cv2.imwrite(out_name, frame)
                findings.append({
                    "vid": vid,
                    "pacific_time": pac_t,
                    "sec": sec,
                    "cam": cam_name,
                    "red_pixels": red_pixels,
                    "img": out_name
                })
                
    cap.release()

with open("red_car_detections/findings.json", "w") as f:
    json.dump(findings, f, indent=2)

print(f"Scan finished! Found {len(findings)} potential red object detections.")
