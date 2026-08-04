import glob
import os
import cv2

files = sorted(glob.glob("real_910am_frames/*v2837102050*.jpg") + glob.glob("real_910am_frames/*v2837101570*.jpg") + glob.glob("real_910am_frames/*v2837101125*.jpg"))

os.makedirs("car_drive_event", exist_ok=True)

for f in files:
    img = cv2.imread(f)
    h, w = img.shape[:2]
    w3 = w // 3
    h2 = h // 2
    # Front camera
    front = img[0:h2, w3:2*w3]
    base = os.path.basename(f)
    cv2.imwrite(f"car_drive_event/{base}", front)

print(f"Saved {len(files)} front frames to car_drive_event.")
