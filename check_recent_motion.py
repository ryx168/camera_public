#!/usr/bin/env python3
import json
import subprocess
import cv2
import os
import datetime
from datetime import timezone
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

# Ensure UTF-8 console output
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

CHECK_AREA = os.environ.get('CHECK_AREA', 'house_around')
TARGET_OBJECT = os.environ.get('TARGET_OBJECT', 'person')

# Initialize HOG people detector safely
try:
    hog = cv2.HOGDescriptor()
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
except AttributeError:
    print("Warning: cv2.HOGDescriptor not available in this OpenCV build. Falling back to motion detection.")
    hog = None


def annotate_and_save_snapshot(frame, crop_roi, bbox, area_name, target_obj, vid, url, timestamp_sec, score, p_height, p_weight, output_path):
    """Draw HUD overlay and detection boxes, and save JPEG screenshot."""
    annotated = frame.copy()
    h, w = annotated.shape[:2]
    
    # Highlight Region of Interest (ROI) with clean bordered rectangle
    if crop_roi is not None:
        rx1, ry1, rx2, ry2 = crop_roi
        cv2.rectangle(annotated, (rx1, ry1), (rx2, ry2), (0, 215, 255), 2)
        # Add small corner tag for ROI
        tag_text = f"ROI: {area_name.upper()}"
        cv2.putText(annotated, tag_text, (rx1 + 4, max(ry1 - 6, 15)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 215, 255), 1, cv2.LINE_AA)
        
        # If person/object bounding box exists (relative to ROI)
        if bbox is not None:
            bx, by, bw, bh = bbox
            px1, py1 = rx1 + bx, ry1 + by
            px2, py2 = px1 + bw, py1 + bh
            # Clip to frame
            px1, py1 = max(0, px1), max(0, py1)
            px2, py2 = min(w - 1, px2), min(h - 1, py2)
            cv2.rectangle(annotated, (px1, py1), (px2, py2), (0, 0, 255), 2)
            cv2.putText(annotated, f"{target_obj.capitalize()} ({p_weight:.2f})", (px1, max(py1 - 6, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1, cv2.LINE_AA)

    # Top HUD banner overlay
    banner_height = 54
    overlay = annotated.copy()
    cv2.rectangle(overlay, (0, 0), (w, banner_height), (15, 15, 25), -1)
    cv2.addWeighted(overlay, 0.85, annotated, 0.15, 0, annotated)
    
    # Red accent line below banner
    cv2.line(annotated, (0, banner_height), (w, banner_height), (0, 0, 220), 2)

    # Banner Text - Line 1: Alert Type & Area
    now_utc_str = datetime.datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line1 = f"[MOTION DETECTED] Area: {area_name.upper()} | Target: {target_obj.upper()} | Time in Video: {timestamp_sec:.1f}s"
    cv2.putText(annotated, line1, (12, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 230, 255), 2, cv2.LINE_AA)
    
    # Banner Text - Line 2: Video ID, Motion Score & Time
    line2 = f"Twitch VOD: {vid} | Motion: {score:,} px | Conf: {p_weight:.2f} | Captured: {now_utc_str}"
    cv2.putText(annotated, line2, (12, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (230, 230, 230), 1, cv2.LINE_AA)

    # Ensure output directory exists and save
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    cv2.imwrite(output_path, annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    print(f"Saved detection screenshot to: {output_path}")


def get_stream_url(vid):
    url = f'https://www.twitch.tv/videos/{vid[1:]}'
    res = subprocess.run([sys.executable, '-m', 'yt_dlp', '-g', url], capture_output=True, text=True)
    return vid, url, res.stdout.strip()


def main():
    # 1. Fetch recent videos
    print("Fetching recent videos metadata...")
    res = subprocess.run([sys.executable, '-m', 'yt_dlp', '--flat-playlist', '--dump-json', '--playlist-items', '1-400', 'https://www.twitch.tv/elarathornfield168/videos?filter=all&sort=time'], capture_output=True, text=True)

    lines = res.stdout.strip().split('\n')
    if not lines or lines[0] == '':
        print("Failed to fetch videos")
        if res.stderr:
            print("yt_dlp stderr:", res.stderr)
        with open("report.txt", "a", encoding="utf-8") as f:
            f.write(f"=== Report for {CHECK_AREA} ({TARGET_OBJECT}) ===\n")
            f.write("no find (failed to fetch video metadata from Twitch)\n\n")
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
        print("No videos found in the last 3 hours. Exiting.")
        with open("report.txt", "a", encoding="utf-8") as f:
            f.write(f"=== Report for {CHECK_AREA} ({TARGET_OBJECT}) ===\n")
            f.write("no videos in the last 3 hours\n\n")
        exit(0)

    print(f"Found {len(recent_videos)} videos in the last 3 hours")
    ids = [v['id'] for v in recent_videos]

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

    # Check Area / Region of Interest (ROI) configuration
    ROI_Y_MIN = float(os.environ.get('ROI_Y_MIN', '0.25'))
    ROI_Y_MAX = float(os.environ.get('ROI_Y_MAX', '1.0'))
    ROI_X_MIN = float(os.environ.get('ROI_X_MIN', '0.0'))
    ROI_X_MAX = float(os.environ.get('ROI_X_MAX', '1.0'))

    video_scores = []
    DIFF_THRESHOLD = int(os.environ.get('DIFF_THRESHOLD', '35'))        # Pixel difference threshold (higher = less sensitive to noise)
    MOTION_THRESHOLD = int(os.environ.get('MOTION_THRESHOLD', '25000')) # Minimum motion pixels (higher = less sensitive)
    MIN_PERSON_HEIGHT = int(os.environ.get('MIN_PERSON_HEIGHT', '110')) # Minimum bounding box height on 800px crop (higher = ignore distant)
    MIN_CONFIDENCE = float(os.environ.get('MIN_CONFIDENCE', '0.70'))    # HOG confidence margin (higher = ignore false positives)

    def get_crop_and_roi(frame):
        h, w = frame.shape[:2]
        if w >= 1280:
            base_x1, base_y1, base_x2, base_y2 = 426, 0, 853, 240
        else:
            base_x1, base_y1, base_x2, base_y2 = w // 3, 0, (w // 3) * 2, h // 2
            
        ch = base_y2 - base_y1
        cw = base_x2 - base_x1
        y1 = base_y1 + int(ch * ROI_Y_MIN)
        y2 = base_y1 + int(ch * ROI_Y_MAX)
        x1 = base_x1 + int(cw * ROI_X_MIN)
        x2 = base_x1 + int(cw * ROI_X_MAX)
        
        crop = frame[y1:y2, x1:x2]
        roi_coords = (x1, y1, x2, y2)
        return crop, roi_coords

    for idx, vid in enumerate(ids):
        if vid not in stream_urls: continue
        url, stream_url = stream_urls[vid]
        
        cap = cv2.VideoCapture(stream_url)
        ret, prev_frame = cap.read()
        if not ret: continue
        
        prev_crop, _ = get_crop_and_roi(prev_frame)
        if prev_crop.size == 0:
            cap.release()
            continue
        prev_gray = cv2.cvtColor(prev_crop, cv2.COLOR_BGR2GRAY)
        
        max_motion = 0
        max_frame_idx = 0
        person_close_detected = False
        best_person_details = None
        best_frame = None
        best_roi = None
        best_bbox = None
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
            
            crop, roi_coords = get_crop_and_roi(frame)
            if crop.size == 0: continue
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            
            diff = cv2.absdiff(prev_gray, gray)
            _, thresh = cv2.threshold(diff, DIFF_THRESHOLD, 255, cv2.THRESH_BINARY)
            
            motion = cv2.countNonZero(thresh)
            if motion > max_motion:
                max_motion = motion
                max_frame_idx = frame_count

            # If frame motion exceeds threshold, run HOG person detection if target is person
            if motion > MOTION_THRESHOLD:
                if TARGET_OBJECT == 'person' and hog is not None:
                    crop_resized = cv2.resize(crop, (800, int(crop.shape[0] * (800 / crop.shape[1]))))
                    rects, weights = hog.detectMultiScale(crop_resized, winStride=(8, 8), padding=(8, 8), scale=1.08)
                    
                    for (rx, ry, rw, rh), weight in zip(rects, weights):
                        # Filter out small/distant detections (far on street/background)
                        if weight >= MIN_CONFIDENCE and rh >= MIN_PERSON_HEIGHT:
                            scale_x = crop.shape[1] / 800.0
                            scale_y = crop.shape[0] / float(crop_resized.shape[0])
                            bbox = (int(rx * scale_x), int(ry * scale_y), int(rw * scale_x), int(rh * scale_y))
                            
                            curr_score = motion
                            if not person_close_detected or curr_score > (best_person_details[0] if best_person_details else 0):
                                person_close_detected = True
                                best_person_details = (motion, frame_count / fps, rh, float(weight))
                                best_frame = frame.copy()
                                best_roi = roi_coords
                                best_bbox = bbox
                            break
                else:
                    curr_score = motion
                    if not person_close_detected or curr_score > (best_person_details[0] if best_person_details else 0):
                        person_close_detected = True
                        best_person_details = (motion, frame_count / fps, 0, 1.0)
                        best_frame = frame.copy()
                        best_roi = roi_coords
                        best_bbox = None
                
            prev_gray = gray

        cap.release()

        if person_close_detected and best_person_details and best_frame is not None:
            motion, timestamp, p_height, p_weight = best_person_details
            video_scores.append((motion, vid, url, timestamp, p_height, p_weight, best_frame, best_roi, best_bbox))
        
        if (idx + 1) % 50 == 0:
            print(f"Processed {idx + 1} videos...")

    video_scores.sort(key=lambda x: x[0], reverse=True)

    snapshot_file = f"snapshot_{CHECK_AREA}.jpg"

    if video_scores:
        score, vid, url, t, h, w_conf, best_frame, best_roi, best_bbox = video_scores[0]
        annotate_and_save_snapshot(
            frame=best_frame,
            crop_roi=best_roi,
            bbox=best_bbox,
            area_name=CHECK_AREA,
            target_obj=TARGET_OBJECT,
            vid=vid,
            url=url,
            timestamp_sec=t,
            score=score,
            p_height=h,
            p_weight=w_conf,
            output_path=snapshot_file
        )

    with open("report.txt", "a", encoding="utf-8") as f:
        f.write(f"=== Report for {CHECK_AREA} ({TARGET_OBJECT}) ===\n")
        if video_scores:
            score, vid, url, t, h, w_conf, _, _, _ = video_scores[0]
            f.write(f"OBJECT FOUND!\n\n")
            f.write(f"Top video: {url} at {t:.1f}s\n")
            f.write(f"Motion Score: {score} pixels (Person height: {h}px, conf: {w_conf:.2f})\n")
            f.write(f"Screenshot: {snapshot_file}\n\n")
            f.write("Other top candidates:\n")
            for i in range(1, min(5, len(video_scores))):
                score, vid, url, t, h, w_conf, _, _, _ = video_scores[i]
                f.write(f"Rank {i+1}: {url} at {t:.1f}s (Score: {score})\n")
        else:
            f.write("no find\n")
        f.write("\n")

    print("Report generated.")


if __name__ == "__main__":
    main()
