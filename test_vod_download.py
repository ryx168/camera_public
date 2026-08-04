import os
import sys
import subprocess

from check_recent_motion import prepare_local_vod

vid = "v2837095825"
url = f"https://www.twitch.tv/videos/{vid[1:]}"
print("Testing yt-dlp -g for", url)

res = subprocess.run([sys.executable, "-m", "yt_dlp", "-g", url], capture_output=True, text=True)
print("Return code:", res.returncode)
print("Stdout:", res.stdout[:200])
print("Stderr:", res.stderr[:200])

print("\nTesting prepare_local_vod...")
v, u, path = prepare_local_vod(vid, "temp_vods")
print("Result:", v, u, path)
if path and os.path.exists(path):
    print(f"File exists: {path} ({os.path.getsize(path)} bytes)")
