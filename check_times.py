import subprocess
import json
import sys
import datetime
from datetime import timezone
import os
import re

def get_pacific_time(dt=None, epoch=None):
    if epoch is not None:
        target_utc = datetime.datetime.fromtimestamp(epoch, tz=timezone.utc)
    elif dt is not None:
        if dt.tzinfo is None:
            target_utc = dt.replace(tzinfo=timezone.utc)
        else:
            target_utc = dt.astimezone(timezone.utc)
    else:
        target_utc = datetime.datetime.now(timezone.utc)
    tz_offset = datetime.timezone(datetime.timedelta(hours=-7), name="PDT")
    return target_utc.astimezone(tz_offset)

print("Fetching fresh video list from Twitch...")
res = subprocess.run([
    sys.executable, '-m', 'yt_dlp',
    '--flat-playlist', '--dump-json', '--playlist-items', '1-200',
    'https://www.twitch.tv/elarathornfield168/videos?filter=all&sort=time'
], capture_output=True, text=True)

lines = res.stdout.strip().split('\n')
videos = []
for l in lines:
    try:
        if l.strip():
            videos.append(json.loads(l))
    except Exception:
        pass

print(f"Total fresh videos: {len(videos)}")

parsed = []
for v in videos:
    epoch = None
    thumb = v.get('thumbnail') or ''
    m = re.search(r'_(\d{9,11})//?thumb', thumb)
    if m:
        epoch = int(m.group(1))
    elif v.get('timestamp'):
        epoch = int(v['timestamp'])
    if epoch:
        pac = get_pacific_time(epoch=epoch)
        parsed.append((epoch, pac, v))

parsed.sort(key=lambda x: x[0], reverse=True)

print("\n--- Videos around 9:00 AM - 9:30 AM PDT today (2026-08-04) ---")
target_videos = []
for ep, pac, v in parsed:
    time_str = pac.strftime('%Y-%m-%d %I:%M:%S %p %Z')
    # Check if today and between 8:50 AM and 9:30 AM
    if pac.strftime('%Y-%m-%d') == '2026-08-04' and 8 <= pac.hour <= 10:
        print(f"ID: {v['id']} | Time: {time_str} | Duration: {v.get('duration')}s")
        target_videos.append((ep, pac, v))

print("\nLatest 10 videos overall:")
for ep, pac, v in parsed[:10]:
    print(f"ID: {v['id']} | Time: {pac.strftime('%Y-%m-%d %I:%M:%S %p %Z')} | Duration: {v.get('duration')}s")
