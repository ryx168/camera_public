import os
import cv2
import json
import numpy as np

vids = [
    ("v2837504902", "05:45:08 PM"),
    ("v2837505787", "05:46:07 PM"),
    ("v2837506667", "05:47:10 PM"),
    ("v2837507520", "05:48:15 PM"),
    ("v2837508370", "05:49:19 PM"),
    ("v2837509194", "05:50:22 PM"),
    ("v2837510112", "05:51:25 PM"),
    ("v2837511174", "05:52:36 PM"),
    ("v2837512129", "05:53:43 PM"),
    ("v2837513050", "05:54:49 PM"),
    ("v2837514048", "05:55:56 PM"),
    ("v2837515133", "05:57:08 PM"),
    ("v2837516178", "05:58:16 PM"),
    ("v2837517335", "05:59:23 PM")
]

os.makedirs("parking_search", exist_ok=True)

for vid, pac_t in vids:
    path = f"temp_vods/{vid}.mp4"
    if not os.path.exists(path): continue
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_count // 2)
    ret, frame = cap.read()
    cap.release()
    if ret:
        front = frame[0:240, 426:853]
        cv2.putText(front, f"{vid} | {pac_t}", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        cv2.imwrite(f"parking_search/{vid}_{pac_t.replace(':','').replace(' ','_')}.jpg", front)

print("Saved frames from 5:45 PM to 6:00 PM!")
