import json, subprocess, datetime, time, os, cv2

def get_upload_time(vid):
    res = subprocess.run(['python', '-m', 'yt_dlp', '--dump-json', f'https://www.twitch.tv/videos/{vid[1:]}'], capture_output=True, text=True)
    if res.stdout:
        info = json.loads(res.stdout)
        return info.get('timestamp') or info.get('release_timestamp') or info.get('epoch')
    return None

data = [json.loads(l) for l in open('videos.json', encoding='utf-16')]
ids = [d['id'] for d in data]

def find_index(target_ts):
    low, high = 0, len(ids) - 1
    best = -1
    while low <= high:
        mid = (low + high) // 2
        ts = get_upload_time(ids[mid])
        if ts is None:
            mid -= 1
            ts = get_upload_time(ids[mid])
            if ts is None: break
        if ts < target_ts:
            high = mid - 1
        else:
            best = mid
            low = mid + 1
    return best

start_ts = datetime.datetime(2026, 7, 25, 15, 0, 0).timestamp()
end_ts = datetime.datetime(2026, 7, 25, 18, 0, 0).timestamp()

print(f"Finding boundaries for {start_ts} to {end_ts}...")
idx_18 = find_index(end_ts)
idx_15 = find_index(start_ts)

# Since ids are newest first, idx_18 (18:00) will be smaller than idx_15 (15:00).
start_idx = idx_18
end_idx = idx_15

print(f"Scanning indices from {start_idx} to {end_idx} (approx {end_idx - start_idx} videos)")

hog = cv2.HOGDescriptor()
hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
os.makedirs('logs/person_frames', exist_ok=True)

found_urls = []

for i in range(start_idx, end_idx + 1):
    vid = ids[i]
    url = f'https://www.twitch.tv/videos/{vid[1:]}'
    
    # download video url
    res = subprocess.run(['python', '-m', 'yt_dlp', '-g', url], capture_output=True, text=True)
    stream_url = res.stdout.strip()
    if not stream_url:
        continue
        
    cap = cv2.VideoCapture(stream_url)
    fps = cap.get(cv2.CAP_PROP_FPS) or 20
    frame_count = 0
    detected = False
    
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
            
        # check every ~2 seconds to speed up
        if frame_count % int(fps * 2) == 0:
            height, width = frame.shape[:2]
            scale = 800 / float(width)
            resized = cv2.resize(frame, (800, int(height * scale)))
            
            rects, weights = hog.detectMultiScale(resized, winStride=(8, 8), padding=(8, 8), scale=1.05)
            valid = [w for w in weights if w >= 0.4]
            
            if len(valid) > 0:
                print(f"--> Person detected in {vid} ({url}) at {frame_count/fps:.1f}s")
                cv2.imwrite(f"logs/person_frames/{vid}_{int(frame_count/fps)}s.jpg", resized)
                found_urls.append((url, frame_count/fps))
                detected = True
                break
                
        frame_count += 1
    cap.release()
    
    if i % 10 == 0:
        print(f"Processed up to index {i} ({url})")

print("Finished scanning.")
with open("logs/detected_persons.txt", "w") as f:
    for url, t in found_urls:
        f.write(f"{url} at {t}s\n")
