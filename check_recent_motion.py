import json, subprocess, cv2, os, datetime, sys
from concurrent.futures import ThreadPoolExecutor, as_completed

# Initialize HOG people detector safely
try:
    hog = cv2.HOGDescriptor()
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
except AttributeError:
    print("Warning: cv2.HOGDescriptor not available in this OpenCV build. Falling back to motion detection.")
    hog = None

# 1. Fetch recent videos
print("Fetching recent videos metadata...")
res = subprocess.run([sys.executable, '-m', 'yt_dlp', '--flat-playlist', '--dump-json', '--playlist-items', '1-400', 'https://www.twitch.tv/elarathornfield168/videos?filter=all&sort=time'], capture_output=True, text=True)

lines = res.stdout.strip().split('\n')
if not lines or lines[0] == '':
    print("Failed to fetch videos")
    if res.stderr:
        print("yt_dlp stderr:", res.stderr)
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

print(f"Found {len(recent_videos)} videos in the last 3 hours")

ids = [v['id'] for v in recent_videos]

def get_stream_url(vid):
    url = f'https://www.twitch.tv/videos/{vid[1:]}'
    res = subprocess.run([sys.executable, '-m', 'yt_dlp', '-g', url], capture_output=True, text=True)
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

print(f"Got {len(stream_urls)} valid streams. Starting motion & person detection...")

video_scores = []
MOTION_THRESHOLD = 12000
MIN_PERSON_HEIGHT = 65  # Minimum bounding box height on 800px crop (ignores distant pedestrians/cars)
MIN_CONFIDENCE = 0.35

for idx, vid in enumerate(ids):
    if vid not in stream_urls: continue
    url, stream_url = stream_urls[vid]
    
    cap = cv2.VideoCapture(stream_url)
    ret, prev_frame = cap.read()
    if not ret: continue
    
    def get_front_crop(frame):
        h, w = frame.shape[:2]
        if w >= 1280:
            crop = frame[0:240, 426:853]
        else:
            crop = frame[0:h//2, w//3:(w//3)*2]
        return crop

    prev_crop = get_front_crop(prev_frame)
    prev_gray = cv2.cvtColor(prev_crop, cv2.COLOR_BGR2GRAY)
    
    max_motion = 0
    max_frame_idx = 0
    person_close_detected = False
    best_person_details = None
    frame_count = 1
    
    fps = cap.get(cv2.CAP_PROP_FPS) or 20
    skip = int(fps // 2)
    if skip < 1: skip = 1
    
    while True:
        for _ in range(skip - 1):
            cap.read()
            frame_count += 1
            
        ret, frame = cap.read()
        if not ret: break
        frame_count += 1
        
        crop = get_front_crop(frame)
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        
        diff = cv2.absdiff(prev_gray, gray)
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        
        motion = cv2.countNonZero(thresh)
        if motion > max_motion:
            max_motion = motion
            max_frame_idx = frame_count

        # If frame motion exceeds threshold, run HOG person detection to verify if person is close to house
        if motion > MOTION_THRESHOLD:
            if hog is not None:
                crop_resized = cv2.resize(crop, (800, int(crop.shape[0] * (800 / crop.shape[1]))))
                rects, weights = hog.detectMultiScale(crop_resized, winStride=(8, 8), padding=(8, 8), scale=1.05)
                
                for (x, y, w, h), weight in zip(rects, weights):
                    # Filter out small/distant detections (far on street/background)
                    if weight >= MIN_CONFIDENCE and h >= MIN_PERSON_HEIGHT:
                        person_close_detected = True
                        best_person_details = (motion, frame_count / fps, h, weight)
                        break
            else:
                person_close_detected = True
                best_person_details = (motion, frame_count / fps, 0, 1.0)
            
        prev_gray = gray

    cap.release()

    if person_close_detected and best_person_details:
        motion, timestamp, p_height, p_weight = best_person_details
        video_scores.append((motion, vid, url, timestamp, p_height, p_weight))
    
    if (idx + 1) % 50 == 0:
        print(f"Processed {idx + 1} videos...")

video_scores.sort(key=lambda x: x[0], reverse=True)

with open("report.txt", "w") as f:
    if video_scores:
        score, vid, url, t, h, w_conf = video_scores[0]
        f.write(f"PERSON FOUND!\n\n")
        f.write(f"Top video: {url} at {t:.1f}s\n")
        f.write(f"Motion Score: {score} pixels (Person height: {h}px, conf: {w_conf:.2f})\n\n")
        f.write("Other top candidates:\n")
        for i in range(1, min(5, len(video_scores))):
            score, vid, url, t, h, w_conf = video_scores[i]
            f.write(f"Rank {i+1}: {url} at {t:.1f}s (Score: {score})\n")
    else:
        f.write("no find\n")

print("Report generated.")
