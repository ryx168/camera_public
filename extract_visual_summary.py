import cv2
import os

os.makedirs("final_car_snapshots", exist_ok=True)

# List of key VODs to extract and inspect
vids_to_inspect = [
    ("v2837527477", "06:09:05 PM PDT", 10.0),
    ("v2837528327", "06:10:07 PM PDT", 15.0),
    ("v2837529137", "06:11:06 PM PDT", 10.0),
    ("v2837535220", "06:18:08 PM PDT", 3.0),
    ("v2837535978", "06:19:05 PM PDT", 27.3),
    ("v2837536823", "06:20:01 PM PDT", 0.6),
    ("v2837538332", "06:21:45 PM PDT", 1.0),
]

for vid, pac_t, t_target in vids_to_inspect:
    path = os.path.join("temp_vods", f"{vid}.mp4")
    if not os.path.exists(path): continue
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    
    frame_no = int(t_target * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
    ret, frame = cap.read()
    cap.release()
    
    if ret:
        # Full frame with watermark
        cv2.putText(frame, f"{vid} | {pac_t} (+{t_target:.1f}s)", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.imwrite(f"final_car_snapshots/full_{vid}_{t_target:.1f}s.jpg", frame)
        
        # Front crop [0:240, 426:853]
        front = frame[0:240, 426:853]
        cv2.imwrite(f"final_car_snapshots/front_{vid}_{t_target:.1f}s.jpg", front)
        
        # Kitchen crop [0:240, 853:1280]
        kitchen = frame[0:240, 853:1280]
        cv2.imwrite(f"final_car_snapshots/kitchen_{vid}_{t_target:.1f}s.jpg", kitchen)
        
        # Office crop [0:240, 0:426]
        office = frame[0:240, 0:426]
        cv2.imwrite(f"final_car_snapshots/office_{vid}_{t_target:.1f}s.jpg", office)

print("Extracted visual snapshots!")
