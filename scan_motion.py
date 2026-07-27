import json, subprocess, datetime, cv2, os

data = [json.loads(l) for l in open('videos.json', encoding='utf-16')]
ids = [d['id'] for d in data]

start_idx = 1565
end_idx = 1847

print(f"Scanning indices from {start_idx} to {end_idx} (approx {end_idx - start_idx} videos)")

hog = cv2.HOGDescriptor()
hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
os.makedirs('logs/person_frames_new', exist_ok=True)

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
            
        # check every ~1 seconds to speed up
        if frame_count % int(fps) == 0:
            height, width = frame.shape[:2]
            
            # Crop to Office (0:426, 0:240) and Front (426:853, 0:240)
            if width >= 1280 and height >= 480:
                office_crop = frame[0:240, 0:426]
                front_crop = frame[0:240, 426:853]
            else:
                # scale proportional
                h2 = height // 2
                w3 = width // 3
                office_crop = frame[0:h2, 0:w3]
                front_crop = frame[0:h2, w3:w3*2]
            
            # Resize crops for better HOG detection
            office_resized = cv2.resize(office_crop, (800, int(office_crop.shape[0] * (800 / office_crop.shape[1]))))
            front_resized = cv2.resize(front_crop, (800, int(front_crop.shape[0] * (800 / front_crop.shape[1]))))
            
            # Detect in Office
            rects_o, weights_o = hog.detectMultiScale(office_resized, winStride=(8, 8), padding=(8, 8), scale=1.05)
            valid_o = [w for w in weights_o if w >= 0.4]
            
            # Detect in Front
            rects_f, weights_f = hog.detectMultiScale(front_resized, winStride=(8, 8), padding=(8, 8), scale=1.05)
            valid_f = [w for w in weights_f if w >= 0.4]
            
            if len(valid_o) > 0 or len(valid_f) > 0:
                loc = "Office" if len(valid_o) > 0 else "Front"
                if len(valid_o) > 0 and len(valid_f) > 0:
                    loc = "Both"
                print(f"--> Person detected in {loc} for {vid} ({url}) at {frame_count/fps:.1f}s")
                cv2.imwrite(f"logs/person_frames_new/{vid}_{int(frame_count/fps)}s_{loc}.jpg", frame)
                found_urls.append((url, frame_count/fps, loc))
                # keep going to see if more frames have it, but skip a few seconds
                frame_count += int(fps * 5)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_count)
                
        frame_count += 1
    cap.release()
    
    if i % 10 == 0:
        print(f"Processed up to index {i} ({url})")

print("Finished scanning.")
with open("logs/detected_persons_new.txt", "w") as f:
    for url, t, loc in found_urls:
        f.write(f"{loc}: {url} at {t}s\n")
