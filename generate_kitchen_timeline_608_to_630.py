import cv2
import os
import glob
import json

os.makedirs("kitchen_timeline_608_630", exist_ok=True)

with open("scratch_610pm_videos.json") as f:
    all_videos = json.load(f)

all_videos.sort(key=lambda x: x.get('epoch', 0))

# Filter VODs between 6:08 PM and 6:30 PM
target_vids = []
for v in all_videos:
    pt = v.get('pacific_time', '')
    if '2026-08-04' in pt:
        h = v.get('hour', 0)
        m = v.get('minute', 0)
        if h == 18 and 8 <= m <= 30:
            target_vids.append(v)

print(f"Found {len(target_vids)} VODs between 6:08 PM and 6:30 PM")

timeline_items = []

for v in target_vids:
    vid = v['id']
    pt = v['pacific_time']
    # Format time nicely e.g. "06:10 PM"
    m_match = v.get('minute', 0)
    s_match = v.get('second', 0)
    time_str = f"6:{m_match:02d}:{s_match:02d} PM"
    
    path = f"temp_vods/{vid}.mp4"
    if not os.path.exists(path):
        continue
        
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # Grab middle frame (~12s)
    mid_sec = 12.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(mid_sec * fps))
    ret, frame = cap.read()
    if not ret:
        cap.release()
        continue
        
    # Cam 3 (Kitchen): [0:240, 853:1280]
    kitchen = frame[0:240, 853:1280].copy()
    
    # Close-up Zoom on the Red Car and Garage entry [100:240, 0:220]
    zoom = kitchen[90:240, 0:220].copy()
    zoom_up = cv2.resize(zoom, (440, 300), interpolation=cv2.INTER_CUBIC)
    
    # Add clear text overlay
    cv2.rectangle(kitchen, (0, 0), (220, 28), (0, 0, 0), -1)
    cv2.putText(kitchen, f"Kitchen: {time_str}", (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
    
    cv2.rectangle(zoom_up, (0, 0), (320, 30), (0, 0, 0), -1)
    cv2.putText(zoom_up, f"Red Car Zoom: {time_str}", (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    
    # Red bounding box around car in Kitchen frame
    cv2.rectangle(kitchen, (5, 140), (100, 235), (0, 0, 255), 2)
    
    full_path = f"kitchen_timeline_608_630/{vid}_full_{m_match:02d}m{s_match:02d}s.jpg"
    zoom_path = f"kitchen_timeline_608_630/{vid}_zoom_{m_match:02d}m{s_match:02d}s.jpg"
    
    cv2.imwrite(full_path, kitchen)
    cv2.imwrite(zoom_path, zoom_up)
    
    timeline_items.append({
        "vid": vid,
        "time": time_str,
        "minute": m_match,
        "full_img": full_path,
        "zoom_img": zoom_path
    })
    
    cap.release()

print(f"Generated {len(timeline_items)} timeline snapshots between 6:08 PM and 6:30 PM!")
