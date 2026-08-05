import cv2
import os

os.makedirs("red_car_624pm", exist_ok=True)

cap = cv2.VideoCapture("temp_vods/v2837540541.mp4") # 6:24 PM PDT
fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

# Extract all frames from 10s to 25s
for f_idx in range(int(10 * fps), int(25 * fps), 2):
    cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
    ret, frame = cap.read()
    if not ret: break
    sec = f_idx / fps
    cv2.imwrite(f"red_car_624pm/frame_t{sec:.1f}s.jpg", frame)

cap.release()
print("Extracted 6:24 PM frames!")
