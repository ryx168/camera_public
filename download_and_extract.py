import os
import subprocess

vids = [
    ("v2837094777", "09_08_34"),
    ("v2837095266", "09_09_19"),
    ("v2837095825", "09_10_07"),
    ("v2837096289", "09_10_48"),
    ("v2837096673", "09_11_26"),
    ("v2837097078", "09_12_03"),
    ("v2837097490", "09_12_40"),
]

os.makedirs("extracted_910am", exist_ok=True)

for vid, t_label in vids:
    mp4 = f"scratch_car_test/{vid}.mp4"
    if not os.path.exists(mp4):
        print(f"Missing {mp4}")
        continue
        
    out_pattern = f"extracted_910am/{t_label}_{vid}_f%02d.jpg"
    cmd = [
        "ffmpeg", "-y", "-i", mp4,
        "-vf", "fps=1",
        "-q:v", "2",
        out_pattern
    ]
    res = subprocess.run(cmd, capture_output=True)
    print(f"Extracted {vid} -> returncode {res.returncode}")

print("Extraction complete.")
