import json, subprocess, cv2, numpy as np, os

data = [json.loads(l) for l in open('videos.json', encoding='utf-16')]
ids = [d['id'] for d in data]

start_idx = 1759
end_idx = 1750

hog = cv2.HOGDescriptor()
hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

os.makedirs('logs/person_frames', exist_ok=True)

for i in range(start_idx, end_idx - 1, -1):
    vid = ids[i]
    url = f'https://www.twitch.tv/videos/{vid[1:]}'
    print(f"Checking {url}")
    
    # download video url
    res = subprocess.run(['python', '-m', 'yt_dlp', '-g', url], capture_output=True, text=True)
    stream_url = res.stdout.strip()
    
    if not stream_url:
        continue
        
    cap = cv2.VideoCapture(stream_url)
    fps = cap.get(cv2.CAP_PROP_FPS) or 20
    frame_count = 0
    
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
            
        # check every 1 second
        if frame_count % int(fps) == 0:
            height, width = frame.shape[:2]
            scale = 800 / float(width)
            resized = cv2.resize(frame, (800, int(height * scale)))
            
            rects, weights = hog.detectMultiScale(resized, winStride=(8, 8), padding=(8, 8), scale=1.05)
            
            valid = [w for w in weights if w >= 0.4]
            if len(valid) > 0:
                print(f"--> Person detected in {vid} at {frame_count/fps}s (confidence: {valid})")
                cv2.imwrite(f"logs/person_frames/{vid}_{int(frame_count/fps)}s.jpg", resized)
                break
                
        frame_count += 1
    cap.release()
print("Done")
