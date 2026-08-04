import cv2
import glob
import os
import pytesseract
import re
from check_recent_motion import prepare_local_vod

# Let's inspect OSD timestamp in front camera for VODs from 09:08 to 09:25
vids = [
    ("v2837094777", "09:08:34"),
    ("v2837095825", "09:10:07"),
    ("v2837097490", "09:12:40"),
    ("v2837099351", "09:15:15"),
    ("v2837101125", "09:17:55"),
    ("v2837102539", "09:20:04"),
    ("v2837104048", "09:22:19"),
]

for vid, twitch_t in vids:
    v, u, path = prepare_local_vod(vid, "temp_vods")
    if not path or not os.path.exists(path):
        continue
    cap = cv2.VideoCapture(path)
    ret, frame = cap.read()
    cap.release()
    if not ret: continue
    
    h, w = frame.shape[:2]
    # Front is top middle [0:h//2, w//3: 2*w//3]
    w3 = w // 3
    h2 = h // 2
    front = frame[0:h2, w3:2*w3]
    
    # In front camera, the timestamp is in the top right corner
    fh, fw = front.shape[:2]
    ts_crop = front[0:30, fw-180:fw]
    cv2.imwrite(f"extracted_910am/ts_{vid}.jpg", ts_crop)
    
    # Also check office timestamp in top left
    office = frame[0:h2, 0:w3]
    ts_office = office[0:35, 0:240]
    cv2.imwrite(f"extracted_910am/ts_office_{vid}.jpg", ts_office)
    
    print(f"VOD {vid} (Twitch upload: {twitch_t}): Saved timestamp crops.")
