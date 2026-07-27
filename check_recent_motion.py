import json, subprocess, cv2, os, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# 1. Fetch recent videos
print("Fetching recent videos metadata...")
res = subprocess.run(['python', '-m', 'yt_dlp', '--flat-playlist', '--dump-json', '--playlist-items', '1-400', 'https://www.twitch.tv/elarathornfield168/videos?filter=all&sort=time'], capture_output=True, text=True)

lines = res.stdout.strip().split('\n')
if not lines or lines[0] == '':
    print("Failed to fetch videos")
    with open("report.txt", "w") as f:
        f.write("no find (failed to fetch video metadata from Twitch)")
    exit(1)

videos = []
for l in lines:
    try:
        videos.append(json.loads(l))
    except:
        pass

# We want videos from the last 3 hours (10800 seconds)
now = datetime.datetime.now().timestamp()
target_epoch = now - (3 * 3600)

recent_videos = []
for v in videos:
    if v.get('epoch') and v['epoch'] >= target_epoch:
        recent_videos.append(v)
    elif v.get('timestamp') and v['timestamp'] >= target_epoch:
        recent_videos.append(v)

if not recent_videos:
    # fallback, maybe timezones are off, just use first 300
    recent_videos = videos[:300]

print(f"Found {len(recent_videos)} videos in the last 3 hours")

ids = [v['id'] for v in recent_videos]

def get_stream_url(vid):
    url = f'https://www.twitch.tv/videos/{vid[1:]}'
    res = subprocess.run(['python', '-m', 'yt_dlp', '-g', url], capture_output=True, text=True)
    return vid, url, res.stdout.strip()

print("Fetching stream URLs in parallel...")
stream_urls = {}
with ThreadPoolExecutor(max_workers=10) as executor:
    futures = {executor.submit(get_stream_url, ids[i]): ids[i] for i in range(len(ids))}
    for i, future in enumerate(as_completed(futures)):
        vid, url, stream_url = future.result()
        if stream_url:
            stream_urls[vid] = (url, stream_url)
        if (i+1) % 50 == 0:
            print(f"Fetched {i+1} URLs...")

print(f"Got {len(stream_urls)} valid streams. Starting motion detection...")

video_scores = []
MOTION_THRESHOLD = 15000

for idx, vid in enumerate(ids):
    if vid not in stream_urls: continue
    url, stream_url = stream_urls[vid]
    
    cap = cv2.VideoCapture(stream_url)
    ret, prev_frame = cap.read()
    if not ret: continue
    
    # Front camera is roughly x=426:853, y=0:240
    def get_front_gray(frame):
        h, w = frame.shape[:2]
        if w >= 1280:
            crop = frame[0:240, 426:853]
        else:
            crop = frame[0:h//2, w//3:(w//3)*2]
        return cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        
    prev_gray = get_front_gray(prev_frame)
    
    max_motion = 0
    max_frame_idx = 0
    frame_count = 1
    
    fps = cap.get(cv2.CAP_PROP_FPS) or 20
    skip = int(fps // 2)
    if skip < 1: skip = 1
    
    while True:
        # Skip frames
        for _ in range(skip - 1):
            cap.read()
            frame_count += 1
            
        ret, frame = cap.read()
        if not ret: break
        frame_count += 1
        
        gray = get_front_gray(frame)
        
        # Calculate absolute difference
        diff = cv2.absdiff(prev_gray, gray)
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        
        motion = cv2.countNonZero(thresh)
        if motion > max_motion:
            max_motion = motion
            max_frame_idx = frame_count
            
        prev_gray = gray

    cap.release()
    video_scores.append((max_motion, vid, url, max_frame_idx / fps))
    
    if (idx + 1) % 50 == 0:
        print(f"Processed {idx + 1} videos...")

video_scores.sort(key=lambda x: x[0], reverse=True)

with open("report.txt", "w") as f:
    if video_scores and video_scores[0][0] > MOTION_THRESHOLD:
        score, vid, url, t = video_scores[0]
        f.write(f"PERSON FOUND!\n\n")
        f.write(f"Top video: {url} at {t:.1f}s\n")
        f.write(f"Motion Score: {score} pixels\n\n")
        f.write("Other top candidates:\n")
        for i in range(1, min(5, len(video_scores))):
            score, vid, url, t = video_scores[i]
            if score > MOTION_THRESHOLD:
                f.write(f"Rank {i+1}: {url} at {t:.1f}s (Score: {score})\n")
    else:
        f.write("no find\n")

print("Report generated.")
