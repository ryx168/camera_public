import cv2
import os
import glob
import json

os.makedirs("kitchen_deep_inspect", exist_ok=True)

with open("scratch_610pm_videos.json") as f:
    all_videos = json.load(f)

# Sort chronologically
all_videos.sort(key=lambda x: x.get('epoch', 0))

# Filter between 5:30 PM and 6:45 PM
sub_vids = []
for v in all_videos:
    pt = v.get('pacific_time', '')
    if '2026-08-04' in pt:
        h = v.get('hour', 0)
        m = v.get('minute', 0)
        if (h == 17 and m >= 30) or (h == 18 and m <= 45):
            sub_vids.append(v)

print(f"Total VODs to deep inspect in Kitchen Cam 3: {len(sub_vids)}")

for v in sub_vids:
    vid = v['id']
    pt = v['pacific_time']
    path = f"temp_vods/{vid}.mp4"
    if not os.path.exists(path): continue
    
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # Check 5 frames per video
    for sec_offset in [0.0, 5.0, 10.0, 15.0, 20.0]:
        f_idx = int(sec_offset * fps)
        if f_idx >= frame_count: break
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
        ret, frame = cap.read()
        if not ret: break
        
        # Cam 3 (Kitchen): [0:240, 853:1280]
        kitchen = frame[0:240, 853:1280]
        
        # Save timestamped Kitchen crop
        clean_time = pt.replace(':','').replace(' ','_')
        out_name = f"kitchen_deep_inspect/{clean_time}_{vid}_t{int(sec_offset)}s.jpg"
        cv2.imwrite(out_name, kitchen)
        
    cap.release()

print("Kitchen Cam 3 deep inspection frames extracted!")
