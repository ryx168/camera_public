import glob
import os
import cv2
import numpy as np

# Find all extracted frames from all videos in 9am
files = sorted(glob.glob("real_910am_frames/*_f01.jpg"))

print("Camera comparison across 09:09:00 to 09:12:40:")
for f in files:
    img = cv2.imread(f)
    base = os.path.basename(f)
    print(f"File: {base}")
