import csv
import subprocess
import os
import sys
from datetime import datetime, timedelta

CSV_FILE = 'sep6_to_sep8_1700_vods.csv'
OUT_DIR = 'frames'
START_TIME = datetime.strptime('2026-09-06 12:53:00', '%Y-%m-%d %H:%M:%S')
END_TIME = datetime.strptime('2026-09-06 23:59:59', '%Y-%m-%d %H:%M:%S')

os.makedirs(OUT_DIR, exist_ok=True)

clips = []
with open(CSV_FILE, 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        # Example format: 2026-09-06 12:00:10 AM
        start_dt = datetime.strptime(row['start_pacific'], '%Y-%m-%d %I:%M:%S %p')
        if START_TIME <= start_dt <= END_TIME:
            clips.append({
                'start': start_dt,
                'id': row['video_id'].replace('v', ''),
                'url': row['url']
            })

# Sort clips by start time
clips.sort(key=lambda x: x['start'])

# Sample every 2 minutes
sampled_clips = []
last_sample_time = None
for clip in clips:
    if last_sample_time is None or (clip['start'] - last_sample_time).total_seconds() >= 120:
        sampled_clips.append(clip)
        last_sample_time = clip['start']

print(f"Total clips in window: {len(clips)}, Sampled every 2 mins: {len(sampled_clips)}")

for clip in sampled_clips:
    dt_str = clip['start'].strftime('%Y%m%d_%H%M%S')
    out_path = os.path.join(OUT_DIR, f"p_{dt_str}.jpg")
    
    if os.path.exists(out_path):
        continue
        
    print(f"Extracting {out_path} from {clip['url']}")
    
    try:
        m3u8_url = subprocess.check_output(
            [sys.executable, '-m', 'yt_dlp', '-g', clip['url']], 
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
        
        subprocess.check_call(
            ['ffmpeg', '-ss', '5', '-i', m3u8_url, '-frames:v', '1', '-y', out_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception as e:
        print(f"Failed to process {clip['url']}: {e}")

print("Extraction complete.")
