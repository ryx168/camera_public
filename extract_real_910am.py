import os
import subprocess
import cv2
from check_recent_motion import prepare_local_vod

vids = [
    ("v2837100234", "09_09_00"),
    ("v2837100681", "09_09_45"),
    ("v2837101125", "09_10_26"),
    ("v2837101570", "09_11_10"),
    ("v2837102050", "09_11_50"),
]

os.makedirs("real_910am_frames", exist_ok=True)

for vid, t_label in vids:
    print(f"Preparing {vid}...")
    v, u, path = prepare_local_vod(vid, "temp_vods")
    if path and os.path.exists(path):
        out_pattern = f"real_910am_frames/{t_label}_{vid}_f%02d.jpg"
        cmd = [
            "ffmpeg", "-y", "-i", path,
            "-vf", "fps=2",
            "-q:v", "2",
            out_pattern
        ]
        subprocess.run(cmd, capture_output=True)
        print(f"Extracted {vid}")

print("Done extracting real 9:10 AM frames.")
