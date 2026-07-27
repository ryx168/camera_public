import json, subprocess, cv2, os
from concurrent.futures import ThreadPoolExecutor, as_completed

data = [json.loads(l) for l in open('videos.json', encoding='utf-16')]
ids = [d['id'] for d in data]

start_idx = 1565
end_idx = 1847

print(f"Scanning indices from {start_idx} to {end_idx} (approx {end_idx - start_idx + 1} videos)")

def get_stream_url(vid):
    url = f'https://www.twitch.tv/videos/{vid[1:]}'
    res = subprocess.run(['python', '-m', 'yt_dlp', '-g', url], capture_output=True, text=True)
    return vid, url, res.stdout.strip()

print("Fetching stream URLs in parallel...")
stream_urls = {}
with ThreadPoolExecutor(max_workers=10) as executor:
    futures = {executor.submit(get_stream_url, ids[i]): ids[i] for i in range(start_idx, end_idx + 1)}
    for i, future in enumerate(as_completed(futures)):
        vid, url, stream_url = future.result()
        if stream_url:
            stream_urls[vid] = (url, stream_url)
        if (i+1) % 50 == 0:
            print(f"Fetched {i+1} URLs...")

print(f"Got {len(stream_urls)} valid streams. Starting motion detection...")

video_scores = []

for idx, vid in enumerate(ids[start_idx:end_idx + 1]):
    if vid not in stream_urls: continue
    url, stream_url = stream_urls[vid]
    
    cap = cv2.VideoCapture(stream_url)
    ret, prev_frame = cap.read()
    if not ret: continue
    
    # Front camera is roughly x=426:853, y=0:240
    # Let's crop to it and convert to grayscale
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
    
    # We will read every Nth frame to speed up (e.g., 2 frames per second)
    skip = int(fps // 2)
    
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

# Sort by motion descending
video_scores.sort(key=lambda x: x[0], reverse=True)

print("\n--- TOP 10 MOTION VIDEOS IN FRONT CAMERA ---")
with open("logs/top_motion.txt", "w") as f:
    for i in range(min(10, len(video_scores))):
        score, vid, url, t = video_scores[i]
        line = f"Rank {i+1}: {url} at {t:.1f}s (Score: {score})"
        print(line)
        f.write(line + "\n")
