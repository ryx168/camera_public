import cv2
import os

os.makedirs("red_car_exact_arrival", exist_ok=True)

# Check VODs from 6:26 PM to 6:30 PM
arrival_vods = [
    ("v2837542180", "6:26 PM"),
    ("v2837542994", "6:27 PM"),
    ("v2837543737", "6:28 PM"),
    ("v2837544415", "6:29 PM"),
    ("v2837545204", "6:30 PM"),
]

for vid, label in arrival_vods:
    mp4_path = f"temp_vods/{vid}.mp4"
    if not os.path.exists(mp4_path): continue
    
    cap = cv2.VideoCapture(mp4_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # Sample every second
    for sec in range(0, int(frame_count / fps), 1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(sec * fps))
        ret, frame = cap.read()
        if not ret: break
        
        # Cam 3 (Kitchen): [0:240, 853:1280]
        kitchen = frame[0:240, 853:1280].copy()
        zoom = kitchen[50:240, 0:300].copy()
        zoom_up = cv2.resize(zoom, (480, 320), interpolation=cv2.INTER_CUBIC)
        
        cv2.rectangle(zoom_up, (0, 0), (360, 32), (0, 0, 0), -1)
        cv2.putText(zoom_up, f"Red Car Entering: {label} (+{sec:02d}s)", (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        
        out_name = f"red_car_exact_arrival/{vid}_{label.replace(':','').replace(' ','_')}_t{sec:02d}s.jpg"
        cv2.imwrite(out_name, zoom_up)
        
    cap.release()

print("Extracted exact arrival sequence!")
