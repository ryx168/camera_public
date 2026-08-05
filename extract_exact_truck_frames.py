import cv2
import os

os.makedirs("car_610pm_detected", exist_ok=True)

# Inspect v2837527477 (6:09 PM), v2837528327 (6:10 PM), v2837529137 (6:11 PM)
for vid, pac_t in [("v2837527477", "06:09:05 PM"), ("v2837528327", "06:10:07 PM"), ("v2837529137", "06:11:06 PM")]:
    path = f"temp_vods/{vid}.mp4"
    if not os.path.exists(path): continue
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # Extract frames at 0s, 5s, 10s, 15s, 20s, 24s, 25s, 30s, 35s, 40s
    for sec in range(0, int(frame_count / fps), 2):
        f_num = int(sec * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_num)
        ret, frame = cap.read()
        if ret:
            # Front camera crop
            front_crop = frame[0:240, 426:853]
            cv2.putText(frame, f"VOD {vid} - {pac_t} (+{sec}s)", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            cv2.imwrite(f"car_610pm_detected/{vid}_t{sec:02d}s_full.jpg", frame)
            cv2.imwrite(f"car_610pm_detected/{vid}_t{sec:02d}s_front.jpg", front_crop)
            
    cap.release()

print("Extracted detailed sequence around 6:10 PM!")
