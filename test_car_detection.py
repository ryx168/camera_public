import os
import sys
import subprocess
import cv2
import numpy as np

os.makedirs("scratch_car_test", exist_ok=True)

# VODs around 9:08 - 9:13 AM PDT
vids = [
    "v2837094777", # 09:08:34
    "v2837095266", # 09:09:19
    "v2837095825", # 09:10:07
    "v2837096289", # 09:10:48
    "v2837096673", # 09:11:26
    "v2837097078", # 09:12:03
    "v2837097490", # 09:12:40
]

for vid in vids:
    url = f"https://www.twitch.tv/videos/{vid[1:]}"
    local_mp4 = f"scratch_car_test/{vid}.mp4"
    if not os.path.exists(local_mp4) or os.path.getsize(local_mp4) < 10000:
        print(f"Downloading {vid} ({url})...")
        cmd = [sys.executable, "-m", "yt_dlp", "-f", "best", "-o", local_mp4, url]
        subprocess.run(cmd, capture_output=True, timeout=120)
    
    if os.path.exists(local_mp4) and os.path.getsize(local_mp4) > 10000:
        print(f"Downloaded {vid}: {os.path.getsize(local_mp4)} bytes")
    else:
        print(f"Failed to download {vid}")

print("Done downloading test clips.")
