import cv2
import os

os.makedirs("vehicle_highlights", exist_ok=True)

# 1. 6:10 PM Truck passing/arriving in v2837528327
cap = cv2.VideoCapture("temp_vods/v2837528327.mp4")
fps = cap.get(cv2.CAP_PROP_FPS) or 20.0

for t in [22.5, 23.0, 23.5, 24.0, 24.5, 25.0]:
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
    ret, frame = cap.read()
    if ret:
        # Full frame
        cv2.putText(frame, f"6:10 PM Truck (VOD v2837528327 +{t}s)", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        cv2.imwrite(f"vehicle_highlights/truck_610pm_{t:.1f}s_full.jpg", frame)
        # Front camera crop
        front = frame[0:240, 426:853]
        cv2.imwrite(f"vehicle_highlights/truck_610pm_{t:.1f}s_front.jpg", front)
        # Top street crop
        street = front[0:140, 0:300]
        cv2.imwrite(f"vehicle_highlights/truck_610pm_{t:.1f}s_street.jpg", street)

cap.release()

# 2. 6:24 PM event in v2837540541
if os.path.exists("temp_vods/v2837540541.mp4"):
    cap2 = cv2.VideoCapture("temp_vods/v2837540541.mp4")
    fps2 = cap2.get(cv2.CAP_PROP_FPS) or 20.0
    for t in [38.0, 39.0, 40.0, 40.5, 41.0, 42.0]:
        cap2.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps2))
        ret, frame = cap2.read()
        if ret:
            cv2.putText(frame, f"6:24 PM Event (VOD v2837540541 +{t}s)", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            cv2.imwrite(f"vehicle_highlights/event_624pm_{t:.1f}s_full.jpg", frame)
            cv2.imwrite(f"vehicle_highlights/event_624pm_{t:.1f}s_front.jpg", frame[0:240, 426:853])
            cv2.imwrite(f"vehicle_highlights/event_624pm_{t:.1f}s_kitchen.jpg", frame[0:240, 853:1280])
    cap2.release()

print("Vehicle highlights extracted successfully!")
