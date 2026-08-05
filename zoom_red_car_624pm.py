import cv2
import os

os.makedirs("red_car_zooms_624pm", exist_ok=True)

cap = cv2.VideoCapture("temp_vods/v2837540541.mp4") # 6:24:26 PM PDT
fps = cap.get(cv2.CAP_PROP_FPS) or 20.0

# 16.0s to 20.0s
for t in [15.5, 16.0, 16.5, 17.0, 17.5, 18.0, 18.5, 19.0]:
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
    ret, frame = cap.read()
    if not ret: continue
    
    # Front camera crop: [0:240, 426:853]
    front = frame[0:240, 426:853]
    # Street zoom: [0:120, 100:350]
    street_zoom = front[0:120, 50:350]
    
    # Kitchen camera crop: [0:240, 853:1280]
    kitchen = frame[0:240, 853:1280]
    
    cv2.imwrite(f"red_car_zooms_624pm/t{t:.1f}s_full.jpg", frame)
    cv2.imwrite(f"red_car_zooms_624pm/t{t:.1f}s_front.jpg", front)
    cv2.imwrite(f"red_car_zooms_624pm/t{t:.1f}s_street.jpg", street_zoom)
    cv2.imwrite(f"red_car_zooms_624pm/t{t:.1f}s_kitchen.jpg", kitchen)

cap.release()
print("Saved zooms for 6:24 PM red car!")
