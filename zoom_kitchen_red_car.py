import cv2
import os

os.makedirs("kitchen_red_car_zooms", exist_ok=True)

# Let's inspect 6:08 PM, 6:09 PM, 6:10 PM, 6:11 PM, 6:12 PM
vods = [
    ("v2837526606", "06:08 PM PDT"),
    ("v2837527477", "06:09 PM PDT"),
    ("v2837528327", "06:10 PM PDT"),
    ("v2837529137", "06:11 PM PDT"),
    ("v2837529844", "06:12 PM PDT")
]

for vid, label in vods:
    mp4_path = f"temp_vods/{vid}.mp4"
    if not os.path.exists(mp4_path): continue
    
    cap = cv2.VideoCapture(mp4_path)
    ret, frame = cap.read()
    if not ret: 
        cap.release()
        continue
    
    # Kitchen camera is [0:240, 853:1280]
    kitchen = frame[0:240, 853:1280].copy()
    
    # Zoom in to the lower-left garage/driveway corner where red vehicle is
    # [120:240, 0:200]
    zoom = kitchen[100:240, 0:200].copy()
    zoom_large = cv2.resize(zoom, (400, 280), interpolation=cv2.INTER_CUBIC)
    
    cv2.putText(kitchen, f"Kitchen Cam 3: {label}", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    cv2.putText(zoom_large, f"Zoom (Garage/Vehicle Entry): {label}", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
    
    cv2.imwrite(f"kitchen_red_car_zooms/{vid}_full_kitchen.jpg", kitchen)
    cv2.imwrite(f"kitchen_red_car_zooms/{vid}_zoom_corner.jpg", zoom_large)
    
    cap.release()

print("Extracted Kitchen camera (Cam 3) full and zoomed views!")
