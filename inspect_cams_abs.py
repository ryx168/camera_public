import cv2
import os

print("Current working dir:", os.getcwd())
base_dir = r"c:\camera"
mp4_path = os.path.join(base_dir, "temp_vods", "v2837095825.mp4")

if not os.path.exists(mp4_path):
    print("MP4 path not found:", mp4_path)
else:
    cap = cv2.VideoCapture(mp4_path)
    ret, frame = cap.read()
    if ret:
        h, w = frame.shape[:2]
        print(f"Frame size: {w}x{h}")
        out_file = os.path.join(base_dir, "test_layout_9_10am.jpg")
        ok = cv2.imwrite(out_file, frame)
        print(f"Saved {out_file}: ok={ok}, size={os.path.getsize(out_file)} bytes")
    cap.release()
