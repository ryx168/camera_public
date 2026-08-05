import subprocess
import json
import re
import datetime
from datetime import timezone

def get_pacific_time(epoch=None):
    if epoch is not None:
        target_utc = datetime.datetime.fromtimestamp(epoch, tz=timezone.utc)
    else:
        target_utc = datetime.datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return target_utc.astimezone(ZoneInfo("America/Los_Angeles"))
    except Exception:
        tz_offset = datetime.timezone(datetime.timedelta(hours=-7), name="PDT")
        return target_utc.astimezone(tz_offset)

print("Fetching video list from Twitch...")
res = subprocess.run([
    'python', '-m', 'yt_dlp',
    '--flat-playlist', '--dump-json', '--playlist-items', '1-200',
    'https://www.twitch.tv/elarathornfield168/videos?filter=all&sort=time'
], capture_output=True, text=True)

videos = []
for line in res.stdout.strip().split('\n'):
    if not line: continue
    try:
        videos.append(json.loads(line))
    except Exception:
        pass

print(f"Total videos fetched: {len(videos)}")

# Parse epochs and filter
target_videos = []
for v in videos:
    thumb = v.get('thumbnail') or ''
    epoch = None
    m = re.search(r'_(\d{9,11})//?thumb', thumb)
    if m:
        epoch = int(m.group(1))
    elif v.get('timestamp'):
        epoch = int(v['timestamp'])
    elif v.get('release_timestamp'):
        epoch = int(v['release_timestamp'])
        
    if epoch:
        dt_pac = get_pacific_time(epoch)
        v['epoch'] = epoch
        v['pacific_time'] = dt_pac.strftime("%Y-%m-%d %I:%M:%S %p %Z")
        v['time_hour_min'] = dt_pac.strftime("%H:%M")
        v['hour'] = dt_pac.hour
        v['minute'] = dt_pac.minute
        v['date'] = dt_pac.strftime("%Y-%m-%d")
        target_videos.append(v)

print(f"Parsed {len(target_videos)} videos with timestamps.")
# Print videos from today between 17:30 and 19:00 (5:30 PM to 7:00 PM)
print("\n--- Videos around 5:30 PM - 7:00 PM PDT ---")
matches = []
for v in target_videos:
    # Print the most recent 40 videos anyway to see current timeline
    pass

for v in target_videos[:40]:
    print(f"ID: {v['id']} | Title: {v.get('title')} | Pacific Time: {v['pacific_time']} | Duration: {v.get('duration')}s")
    if "17:" <= v['time_hour_min'] <= "19:00" or "05:" in v['pacific_time'] or "06:" in v['pacific_time']:
        matches.append(v)

print(f"\nFound {len(matches)} matching videos around 6 PM:")
for m in matches:
    print(f"  {m['id']} - {m['pacific_time']} - {m.get('url', 'https://www.twitch.tv/videos/' + m['id'].replace('v',''))}")

with open("scratch_610pm_videos.json", "w") as f:
    json.dump(target_videos, f, indent=2)
