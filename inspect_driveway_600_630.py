import os
import glob
import cv2
import json

os.makedirs("driveway_inspect_6pm", exist_ok=True)

# Look at all VODs between 6:00 PM and 6:30 PM
with open("scratch_610pm_videos.json") as f:
    all_videos = json.load(f)

vids_map = {v['id']: v for v in all_videos}

target_vids = [
    "v2837518857", # 06:00:32 PM
    "v2837520270", # 06:01:44 PM
    "v2837521587", # 06:02:57 PM
    "v2837522808", # 06:04:10 PM
    "v2837523729", # 06:05:11 PM
    "v2837524781", # 06:06:13 PM
    "v2837525711", # 06:07:08 PM
    "v2837526606", # 06:08:06 PM
    "v2837527477", # 06:09:05 PM
    "v2837528327", # 06:10:07 PM
    "v2837529137", # 06:11:06 PM
    "v2837529844", # 06:11:57 PM
    "v2837530574", # 06:12:45 PM
    "v2837531341", # 06:13:34 PM
    "v2837532048", # 06:14:23 PM
    "v2837532825", # 06:15:18 PM
    "v2837533670", # 06:16:14 PM
    "v2837534496", # 06:17:11 PM
    "v2837535220", # 06:18:08 PM
    "v2837535978", # 06:19:05 PM
    "v2837536823", # 06:20:01 PM
    "v2837537558", # 06:20:52 PM
    "v2837538332", # 06:21:45 PM
    "v2837539043", # 06:22:37 PM
    "v2837539783", # 06:23:31 PM
    "v2837540541", # 06:24:26 PM
    "v2837541368", # 06:25:29 PM
]

for vid in target_vids:
    meta = vids_map.get(vid, {})
    pac_t = meta.get('pacific_time', vid)
    path = f"temp_vods/{vid}.mp4"
    if not os.path.exists(path): continue
    
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # Save a sequence of images every 5 seconds for both Kitchen and Front
    for sec in range(0, int(frame_count / fps), 5):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(sec * fps))
        ret, frame = cap.read()
        if ret:
            # Full composite
            cv2.putText(frame, f"{vid} | {pac_t} (+{sec}s)", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            cv2.imwrite(f"driveway_inspect_6pm/{vid}_t{sec:02d}s.jpg", frame)
    cap.release()

print("Extracted 6:00 PM - 6:25 PM sequence!")
