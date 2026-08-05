import cv2
import os

os.makedirs("kitchen_focus_events", exist_ok=True)

# 1. 6:10 PM (v2837528327)
cap = cv2.VideoCapture("temp_vods/v2837528327.mp4")
fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
for s in [0, 5, 10, 15, 20, 24]:
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(s * fps))
    ret, f = cap.read()
    if ret:
        k = f[0:240, 853:1280]
        cv2.putText(k, f"Kitchen 6:10 PM (+{s}s)", (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        cv2.imwrite(f"kitchen_focus_events/kitchen_610pm_t{s}s.jpg", k)
cap.release()

# 2. 6:27 PM (v2837542994)
if os.path.exists("temp_vods/v2837542994.mp4"):
    cap = cv2.VideoCapture("temp_vods/v2837542994.mp4")
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    for s in [0, 5, 10, 15, 20, 24]:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(s * fps))
        ret, f = cap.read()
        if ret:
            k = f[0:240, 853:1280]
            cv2.putText(k, f"Kitchen 6:27 PM (+{s}s)", (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            cv2.imwrite(f"kitchen_focus_events/kitchen_627pm_t{s}s.jpg", k)
    cap.release()

print("Extracted Kitchen focus frames for 6:10 PM and 6:27 PM!")
