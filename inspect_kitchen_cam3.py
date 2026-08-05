import cv2
import os
import glob

os.makedirs("kitchen_cam3_inspection", exist_ok=True)

# List of VODs around 6:05 PM to 6:20 PM
vods = [
    ("v2837523729", "06:05 PM"),
    ("v2837524781", "06:06 PM"),
    ("v2837525711", "06:07 PM"),
    ("v2837526606", "06:08 PM"),
    ("v2837527477", "06:09 PM"),
    ("v2837528327", "06:10 PM"),
    ("v2837529137", "06:11 PM"),
    ("v2837529844", "06:12 PM"),
    ("v2837530574", "06:13 PM"),
    ("v2837531341", "06:14 PM"),
    ("v2837532048", "06:15 PM"),
    ("v2837532825", "06:16 PM"),
    ("v2837533670", "06:17 PM"),
    ("v2837534496", "06:18 PM"),
    ("v2837535220", "06:19 PM"),
    ("v2837535978", "06:20 PM"),
]

for vid, label in vods:
    mp4_path = f"temp_vods/{vid}.mp4"
    if not os.path.exists(mp4_path): continue
    
    cap = cv2.VideoCapture(mp4_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # Sample every 5 seconds or whenever motion occurs in Kitchen camera
    prev_k_gray = None
    
    for f_idx in range(0, frame_count, int(fps * 2)): # Every 2 seconds
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
        ret, frame = cap.read()
        if not ret: break
        
        sec = f_idx / fps
        
        # Third camera: Kitchen is top-right: [0:240, 853:1280]
        # Let's crop full Kitchen camera with label
        kitchen = frame[0:240, 853:1280].copy()
        
        # Let's compute motion specifically in Kitchen view
        k_gray = cv2.cvtColor(kitchen, cv2.COLOR_BGR2GRAY)
        motion_score = 0
        if prev_k_gray is not None:
            diff = cv2.absdiff(prev_k_gray, k_gray)
            _, th = cv2.threshold(diff, 20, 255, cv2.THRESH_BINARY)
            motion_score = int(cv2.countNonZero(th))
        prev_k_gray = k_gray
        
        # Save snapshot
        cv2.putText(kitchen, f"{label} (+{sec:.0f}s) m:{motion_score}", (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        out_name = f"kitchen_cam3_inspection/{vid}_t{int(sec):02d}s_{label.replace(':','').replace(' ','_')}.jpg"
        cv2.imwrite(out_name, kitchen)

    cap.release()

print("Extracted Kitchen (Cam 3) high-res inspection frames!")
