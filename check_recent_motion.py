#!/usr/bin/env python3
"""
check_recent_motion.py
Scans recent Twitch VODs for motion and person/car activity.
Detects camera count and layout by reading corner text labels ('Office', 'Front', 'Kitchen'/'Kichen', 'Balcony', 'Backyard').
Matches the same camera screen across frames and rejects cross-layout comparisons.
Performs temporal multi-frame motion verification across at least 3 frames to reject
static false positives (railings, tree trunks, gates, posts) and generates a 3-frame
composite group snapshot illustrating object displacement over time.
"""

import json
import subprocess
import cv2
import numpy as np
import os
import re
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

CHECK_AREA = os.environ.get('CHECK_AREA', 'house_around').lower().strip()
TARGET_OBJECT = os.environ.get('TARGET_OBJECT', 'person')

# Initialize pytesseract if available
try:
    import pytesseract
    if os.path.exists(r'C:\Program Files\Tesseract-OCR\tesseract.exe'):
        pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    elif os.path.exists(r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe'):
        pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe'
except ImportError:
    pytesseract = None

# Initialize HOG people detector safely
try:
    hog = cv2.HOGDescriptor()
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
except AttributeError:
    print("Warning: cv2.HOGDescriptor not available in this OpenCV build. Falling back to motion detection.")
    hog = None

# Camera text keywords and synonyms for corner label matching
KNOWN_CAMERAS = {
    'office': ['office', 'offi', 'offic', 'ffice', 'pice'],
    'front': ['front', 'fron', 'ront'],
    'kitchen': ['kitchen', 'kichen', 'kitch', 'itchen', 'chen'],
    'balcony': ['balcony', 'balc', 'alcony', 'cony'],
    'backyard': ['backyard', 'back', 'yard', 'ackyard', 'kyard']
}

# Alias mapping from check_area / env vars to canonical camera names
ALIAS_TO_CANONICAL = {
    'office': 'office', 'cam1': 'office',
    'front': 'front', 'cam2': 'front', 'house_around': 'front', 'door': 'front', 'house': 'front',
    'kitchen': 'kitchen', 'kichen': 'kitchen', 'garage': 'kitchen', 'cam3': 'kitchen', 'car': 'kitchen', 'driveway': 'kitchen',
    'balcony': 'balcony', 'cam4': 'balcony',
    'backyard': 'backyard', 'cam5': 'backyard', 'yard': 'backyard'
}


def extract_corner_label(crop):
    """
    Extracts camera text label (Office, Front, Kitchen/Kichen, Balcony, Backyard)
    from a corner crop using multi-threshold OCR and keyword matching.
    """
    if crop is None or crop.size == 0 or crop.shape[0] < 10 or crop.shape[1] < 10:
        return None
    if pytesseract is None:
        return None

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop

    # Try multiple threshold values and PSM modes
    for th_val in [170, 140, 200, 110]:
        _, th = cv2.threshold(gray, th_val, 255, cv2.THRESH_BINARY)
        th_inv = 255 - th
        resized = cv2.resize(th_inv, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)

        for psm in [7, 6, 8]:
            try:
                txt = pytesseract.image_to_string(resized, config=f'--psm {psm}').lower()
            except Exception:
                return None
            clean_txt = re.sub(r'[^a-z]', '', txt)
            for cam_key, synonyms in KNOWN_CAMERAS.items():
                for syn in synonyms:
                    if syn in clean_txt:
                        return cam_key
    return None


def detect_cameras_from_frame(frame):
    """
    Detects active cameras and their bounding boxes by inspecting corner text
    (Office, Front, Kitchen, Balcony, Backyard) across potential grid layouts.
    Returns: (camera_map, cam_count, layout_name)
    where camera_map = { 'office': (x1, y1, x2, y2), 'front': (x1, y1, x2, y2), ... }
    """
    if frame is None or frame.size == 0:
        return {}, 0, 'none'
    h, w = frame.shape[:2]
    if w < 320 or h < 160:
        return {}, 0, 'none'

    h2 = h // 2
    w3 = w // 3
    w2 = w // 2

    # Candidate layout definitions: list of (slot_name, (x1, y1, x2, y2))
    layout_candidates = {
        5: [
            ('top_left', (0, 0, w3, h2)),
            ('top_mid', (w3, 0, 2*w3, h2)),
            ('top_right', (2*w3, 0, w, h2)),
            ('bot_left', (0, h2, w2, h)),
            ('bot_right', (w2, h2, w, h)),
        ],
        4: [
            ('top_left', (0, 0, w2, h2)),
            ('top_right', (w2, 0, w, h2)),
            ('bot_left', (0, h2, w2, h)),
            ('bot_right', (w2, h2, w, h)),
        ],
        3: [
            ('top_left', (0, 0, w2, h2)),
            ('top_right', (w2, 0, w, h2)),
            ('bot_wide', (0, h2, w, h)),
        ],
        2: [
            ('left', (0, 0, w2, h)),
            ('right', (w2, 0, w, h)),
        ],
        1: [
            ('fullscreen', (0, 0, w, h)),
        ]
    }

    best_layout = None
    best_map = {}
    best_count = 0
    best_ratio = 0.0

    # Test candidate layouts from 5 down to 1
    for num_cams in [5, 4, 3, 2, 1]:
        slots = layout_candidates[num_cams]
        curr_map = {}
        for _, (x1, y1, x2, y2) in slots:
            crop_corner = frame[y1+5:min(y1+40, y2), x1+5:min(x1+130, x2)]
            label = extract_corner_label(crop_corner)
            if label:
                curr_map[label] = (x1, y1, x2, y2)

        match_count = len(curr_map)
        match_ratio = match_count / float(num_cams)

        # Perfect 100% match on all layout slots
        if match_count == num_cams:
            return curr_map, num_cams, f'{num_cams}-cam'

        # Otherwise track best score (prefer higher match count and higher ratio)
        if match_count > best_count or (match_count == best_count and match_ratio > best_ratio):
            best_count = match_count
            best_map = curr_map
            best_layout = num_cams
            best_ratio = match_ratio

    # Fallback to geometric discontinuity detection if OCR returned 0 cameras
    if best_count == 0:
        geom_count = detect_camera_layout_geometric(frame)
        if geom_count > 0:
            return {}, geom_count, f'{geom_count}-cam'

    final_count = best_layout or best_count
    return best_map, final_count, f'{final_count}-cam'


def detect_camera_layout_geometric(frame):
    """
    Geometric pixel-difference fallback to detect grid layout (5, 4, 3, 2, 1, 0).
    """
    if frame is None or frame.size == 0:
        return 0
    h, w = frame.shape[:2]
    if w < 320 or h < 160:
        return 0

    mid_y = h // 2
    w3 = w // 3
    w3_2 = (w // 3) * 2
    w2 = w // 2

    h_top = frame[mid_y-8:mid_y-2, int(w*0.05):int(w*0.95)]
    h_bot = frame[mid_y+2:mid_y+8, int(w*0.05):int(w*0.95)]
    diff_h = float(np.mean(cv2.absdiff(h_top, h_bot)))

    top_y1, top_y2 = int(h * 0.05), mid_y - int(h * 0.05)
    diff_top_w3 = float(np.mean(cv2.absdiff(
        frame[top_y1:top_y2, w3-8:w3-2],
        frame[top_y1:top_y2, w3+2:w3+8]
    )))
    diff_top_w3_2 = float(np.mean(cv2.absdiff(
        frame[top_y1:top_y2, w3_2-8:w3_2-2],
        frame[top_y1:top_y2, w3_2+2:w3_2+8]
    )))
    diff_top_w2 = float(np.mean(cv2.absdiff(
        frame[top_y1:top_y2, w2-8:w2-2],
        frame[top_y1:top_y2, w2+2:w2+8]
    )))

    bot_y1, bot_y2 = mid_y + int(h * 0.05), h - int(h * 0.05)
    diff_bot_w2 = float(np.mean(cv2.absdiff(
        frame[bot_y1:bot_y2, w2-8:w2-2],
        frame[bot_y1:bot_y2, w2+2:w2+8]
    )))

    has_h_split = diff_h > 14.0
    score_top_3col = (diff_top_w3 + diff_top_w3_2) / 2.0
    score_top_2col = diff_top_w2
    has_bot_2col = diff_bot_w2 > 14.0

    if has_h_split:
        if score_top_3col > 15.0 and (score_top_3col > score_top_2col * 1.1 or score_top_2col < 18.0):
            return 5
        elif score_top_2col > 14.0:
            if has_bot_2col:
                return 4
            else:
                return 3
        else:
            if score_top_3col > score_top_2col:
                return 5
            elif has_bot_2col:
                return 4
            else:
                return 3
    else:
        diff_v_full = float(np.mean(cv2.absdiff(
            frame[int(h*0.1):int(h*0.9), w2-8:w2-2],
            frame[int(h*0.1):int(h*0.9), w2+2:w2+8]
        )))
        if diff_v_full > 14.0:
            return 2
        else:
            return 1


def detect_camera_layout(frame):
    """
    Detects camera layout count (5, 4, 3, 2, 1, 0) using text recognition + geometric fallback.
    """
    _, count, _ = detect_cameras_from_frame(frame)
    return count


def is_multicam_grid(frame):
    """
    Returns True if the frame is a multi-camera grid layout (5, 4, or 3 cameras), False otherwise.
    """
    layout = detect_camera_layout(frame)
    return layout in [5, 4, 3]


def get_camera_bounds(frame, area_name, camera_map=None, cam_count=None):
    """
    Returns (cam_x1, cam_y1, cam_x2, cam_y2) for the requested camera zone
    by matching the canonical camera name against detected corner text or grid layout.
    """
    if frame is None or frame.size == 0:
        return None
    h, w = frame.shape[:2]

    canonical = ALIAS_TO_CANONICAL.get(area_name.lower().strip(), area_name.lower().strip())

    # 1. Check if camera was directly detected via corner text
    if camera_map and canonical in camera_map:
        return camera_map[canonical]

    # 2. Geometric / Grid mapping fallback
    if cam_count is None:
        cam_count = detect_camera_layout(frame)

    if cam_count == 5:
        if canonical == 'office':
            return 0, 0, w // 3, h // 2
        elif canonical == 'front':
            return w // 3, 0, (w // 3) * 2, h // 2
        elif canonical == 'kitchen':
            return (w // 3) * 2, 0, w, h // 2
        elif canonical == 'balcony':
            return 0, h // 2, w // 2, h
        elif canonical == 'backyard':
            return w // 2, h // 2, w, h
        else:
            return w // 3, 0, (w // 3) * 2, h // 2

    elif cam_count == 4:
        if canonical == 'office':
            return 0, 0, w // 2, h // 2
        elif canonical == 'front':
            return w // 2, 0, w, h // 2
        elif canonical == 'kitchen':
            return 0, h // 2, w // 2, h
        elif canonical in ['balcony', 'backyard']:
            return w // 2, h // 2, w, h
        else:
            return w // 2, 0, w, h // 2

    elif cam_count == 3:
        if canonical == 'office':
            return 0, 0, w // 2, h // 2
        elif canonical == 'front':
            return w // 2, 0, w, h // 2
        elif canonical == 'kitchen':
            return 0, h // 2, w, h
        elif canonical in ['balcony', 'backyard']:
            return None
        else:
            return w // 2, 0, w, h // 2

    elif cam_count == 2:
        if canonical == 'office':
            return 0, 0, w // 2, h
        elif canonical == 'front':
            return w // 2, 0, w, h
        else:
            return None

    elif cam_count == 1:
        return 0, 0, w, h

    return None


def verify_moving_event(candidates, min_move_px=25.0):
    """
    Temporal verification across at least 3 detection frames:
    Calculates spatial displacement of candidate bounding box centers.
    Ensures all candidate frames in a cluster belong to the SAME camera layout and matching camera slot.
    If displacement < min_move_px, the candidate is a static false positive (railing, tree, gate).
    Returns (is_valid, [start_frame, mid_frame, end_frame], max_displacement).
    """
    if len(candidates) < 3:
        return False, None, 0.0

    # Cluster detections that occur close in time (within 4 seconds) AND have the exact same camera count & slot bounds
    clusters = []
    curr_cluster = [candidates[0]]
    for c in candidates[1:]:
        time_diff = c['time'] - curr_cluster[-1]['time']
        same_layout = c.get('cam_count') == curr_cluster[-1].get('cam_count')
        same_slot = c.get('cam_slot') == curr_cluster[-1].get('cam_slot')
        if time_diff <= 4.0 and same_layout and same_slot:
            curr_cluster.append(c)
        else:
            if len(curr_cluster) >= 3:
                clusters.append(curr_cluster)
            curr_cluster = [c]
    if len(curr_cluster) >= 3:
        clusters.append(curr_cluster)

    if not clusters:
        # Fallback: check if entire candidate list is within 8s and all have the exact same layout and slot
        same_all = all(
            c.get('cam_count') == candidates[0].get('cam_count') and
            c.get('cam_slot') == candidates[0].get('cam_slot')
            for c in candidates
        )
        if same_all and (candidates[-1]['time'] - candidates[0]['time'] <= 8.0) and len(candidates) >= 3:
            clusters = [candidates]
        else:
            return False, None, 0.0

    best_cluster = None
    best_move = 0.0

    for cluster in clusters:
        centers = [c['center'] for c in cluster]
        max_dist = 0.0
        for i in range(len(centers)):
            for j in range(i + 1, len(centers)):
                dx = centers[i][0] - centers[j][0]
                dy = centers[i][1] - centers[j][1]
                dist = float(np.sqrt(dx * dx + dy * dy))
                if dist > max_dist:
                    max_dist = dist

        if max_dist > best_move:
            best_move = max_dist
            best_cluster = cluster

    if best_cluster is None or best_move < min_move_px:
        return False, None, best_move

    c_start = dict(best_cluster[0])
    c_end = dict(best_cluster[-1])

    mid_candidates = best_cluster[1:-1]
    if mid_candidates:
        c_mid = dict(max(mid_candidates, key=lambda x: (x.get('motion', 0), x.get('weight', 0))))
    else:
        c_mid = dict(best_cluster[len(best_cluster) // 2])

    c_start['phase'] = 'START'
    c_mid['phase'] = 'PEAK'
    c_end['phase'] = 'END'

    return True, [c_start, c_mid, c_end], best_move


def annotate_and_save_group_snapshot(three_frames_data, area_name, target_obj, vid, url, total_movement_px, output_path):
    """
    Builds a single 3-frame composite group image showing the object moving
    across 3 distinct time points, with master HUD header and per-frame tracking labels.
    """
    annotated_frames = []

    for idx, item in enumerate(three_frames_data):
        frame = item['frame'].copy()
        h, w = frame.shape[:2]
        crop_roi = item['roi']
        bbox = item['bbox']
        t_sec = item['time']
        phase = item.get('phase', f'FRAME {idx+1}')
        conf = item.get('weight', 1.0)
        cx, cy = item.get('center', (0, 0))
        motion_px = item.get('motion', 0)
        cam_name = item.get('cam_name', area_name)

        # 1. Highlight ROI
        if crop_roi is not None:
            rx1, ry1, rx2, ry2 = crop_roi
            cv2.rectangle(frame, (rx1, ry1), (rx2, ry2), (0, 215, 255), 2)
            cv2.putText(frame, f"CAMERA: {cam_name.upper()} | ROI", (rx1 + 4, max(ry1 - 6, 15)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 215, 255), 1, cv2.LINE_AA)

            # 2. Highlight moving object bounding box
            if bbox is not None:
                bx, by, bw, bh = bbox
                px1, py1 = rx1 + bx, ry1 + by
                px2, py2 = px1 + bw, py1 + bh
                px1, py1 = max(0, px1), max(0, py1)
                px2, py2 = min(w - 1, px2), min(h - 1, py2)
                cv2.rectangle(frame, (px1, py1), (px2, py2), (0, 0, 255), 2)
                label_txt = f"{target_obj.capitalize()} ({conf:.2f}) Pos:({int(cx)},{int(cy)})"
                cv2.putText(frame, label_txt, (px1, max(py1 - 6, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1, cv2.LINE_AA)

        # 3. Sub-header bar on individual frame
        sub_bar_h = 32
        sub_overlay = frame.copy()
        cv2.rectangle(sub_overlay, (0, 0), (w, sub_bar_h), (20, 20, 30), -1)
        cv2.addWeighted(sub_overlay, 0.75, frame, 0.25, 0, frame)
        cv2.line(frame, (0, sub_bar_h), (w, sub_bar_h), (0, 180, 255), 1)

        cam_count = item.get('cam_count', 5)
        sub_text = f"FRAME {idx+1}/3 [{phase}] ({cam_name.upper()} in {cam_count}-Cam Layout) | Time: {t_sec:.1f}s | Target Pos: ({int(cx)}, {int(cy)}) | Motion: {motion_px:,} px"
        cv2.putText(frame, sub_text, (10, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (255, 255, 255), 1, cv2.LINE_AA)

        annotated_frames.append(frame)

    # Master Composite: Stack 3 frames vertically with master header
    frame_h, frame_w = annotated_frames[0].shape[:2]
    header_h = 60
    divider_h = 4
    total_h = header_h + (frame_h * 3) + (divider_h * 2)

    composite = np.zeros((total_h, frame_w, 3), dtype=np.uint8)

    # Master Header background
    cv2.rectangle(composite, (0, 0), (frame_w, header_h), (12, 12, 22), -1)
    cv2.line(composite, (0, header_h), (frame_w, header_h), (0, 0, 230), 2)

    # Master Header text
    t1 = three_frames_data[0]['time']
    t2 = three_frames_data[1]['time']
    t3 = three_frames_data[2]['time']
    cam_count = three_frames_data[0].get('cam_count', 5)
    cam_name = three_frames_data[0].get('cam_name', area_name)
    now_utc_str = datetime.datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    line1 = f"[CONFIRMED MOVING EVENT] Camera: {cam_name.upper()} | Target: {target_obj.upper()} | Layout: {cam_count}-Cam Grid | Movement: {total_movement_px:.1f} px across 3 frames"
    cv2.putText(composite, line1, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 235, 255), 2, cv2.LINE_AA)

    line2 = f"Twitch VOD: {vid} | Multi-Frame Sequence: {t1:.1f}s -> {t2:.1f}s -> {t3:.1f}s | Captured: {now_utc_str}"
    cv2.putText(composite, line2, (12, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (220, 220, 220), 1, cv2.LINE_AA)

    # Place the 3 frames
    curr_y = header_h
    for idx, f_img in enumerate(annotated_frames):
        composite[curr_y : curr_y + frame_h, 0 : frame_w] = f_img
        curr_y += frame_h
        if idx < 2:
            cv2.rectangle(composite, (0, curr_y), (frame_w, curr_y + divider_h), (0, 160, 255), -1)
            curr_y += divider_h

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    cv2.imwrite(output_path, composite, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    print(f"Saved 3-frame group motion snapshot to: {output_path}")


def get_stream_url(vid):
    url = f'https://www.twitch.tv/videos/{vid[1:]}'
    res = subprocess.run([sys.executable, '-m', 'yt_dlp', '-g', url], capture_output=True, text=True)
    return vid, url, res.stdout.strip()


def main():
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
        except Exception:
            pass

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

    canonical_area = ALIAS_TO_CANONICAL.get(CHECK_AREA, CHECK_AREA)
    print(f"Got {len(stream_urls)} valid streams. Starting motion & temporal tracking for camera '{canonical_area}' (alias '{CHECK_AREA}')...")

    # Region of Interest (ROI) within selected camera bounds
    default_roi_y_min = '0.20' if canonical_area == 'front' else '0.0'
    ROI_Y_MIN = float(os.environ.get('ROI_Y_MIN', default_roi_y_min))
    ROI_Y_MAX = float(os.environ.get('ROI_Y_MAX', '1.0'))
    ROI_X_MIN = float(os.environ.get('ROI_X_MIN', '0.0'))
    ROI_X_MAX = float(os.environ.get('ROI_X_MAX', '1.0'))

    DIFF_THRESHOLD = int(os.environ.get('DIFF_THRESHOLD', '35'))
    MOTION_THRESHOLD = int(os.environ.get('MOTION_THRESHOLD', '25000'))
    MIN_PERSON_HEIGHT = int(os.environ.get('MIN_PERSON_HEIGHT', '100'))
    MIN_CONFIDENCE = float(os.environ.get('MIN_CONFIDENCE', '0.60'))
    MIN_MOVEMENT_PX = float(os.environ.get('MIN_MOVEMENT_PX', '25.0'))

    def get_crop_and_roi(frame, camera_map=None, cam_count=None):
        bounds = get_camera_bounds(frame, canonical_area, camera_map=camera_map, cam_count=cam_count)
        if bounds is None:
            return np.empty((0, 0, 3), dtype=np.uint8), None, None
        bx1, by1, bx2, by2 = bounds
        cw = bx2 - bx1
        ch = by2 - by1

        y1 = by1 + int(ch * ROI_Y_MIN)
        y2 = by1 + int(ch * ROI_Y_MAX)
        x1 = bx1 + int(cw * ROI_X_MIN)
        x2 = bx1 + int(cw * ROI_X_MAX)

        crop = frame[y1:y2, x1:x2]
        roi_coords = (x1, y1, x2, y2)
        return crop, roi_coords, bounds

    verified_video_events = []

    for idx, vid in enumerate(ids):
        if vid not in stream_urls: continue
        url, stream_url = stream_urls[vid]

        cap = cv2.VideoCapture(stream_url)
        ret, prev_frame = cap.read()
        if not ret:
            cap.release()
            continue

        # Step 1: Detect initial camera layout and matching camera corner text
        init_cam_map, init_cam_count, init_layout = detect_cameras_from_frame(prev_frame)
        if init_cam_count not in [5, 4, 3, 2, 1]:
            print(f"Skipping {vid}: Detected {init_cam_count} cameras (not a supported layout).")
            cap.release()
            continue

        prev_crop, _, prev_slot = get_crop_and_roi(prev_frame, camera_map=init_cam_map, cam_count=init_cam_count)
        if prev_crop.size == 0:
            print(f"Skipping {vid}: Target camera '{canonical_area}' not found in {init_layout} layout.")
            cap.release()
            continue

        prev_gray = cv2.cvtColor(prev_crop, cv2.COLOR_BGR2GRAY)
        prev_cam_count = init_cam_count

        frame_candidates = []
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

            # Step 2: Detect camera layout & corner text of current screen
            curr_cam_map, curr_cam_count, curr_layout = detect_cameras_from_frame(frame)
            if curr_cam_count not in [5, 4, 3, 2, 1]:
                prev_gray = None
                prev_cam_count = None
                prev_slot = None
                continue

            crop, roi_coords, curr_slot = get_crop_and_roi(frame, camera_map=curr_cam_map, cam_count=curr_cam_count)
            if crop.size == 0:
                prev_gray = None
                prev_cam_count = None
                prev_slot = None
                continue

            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

            # Step 3: CRITICAL - Match EXACT SAME camera screen & prevent cross-layout diffs
            if prev_cam_count is None or curr_cam_count != prev_cam_count or prev_slot != curr_slot or prev_gray is None:
                # Screen layout or camera slot changed; establish new baseline without diffing across different screens
                prev_gray = gray
                prev_cam_count = curr_cam_count
                prev_slot = curr_slot
                continue

            diff = cv2.absdiff(prev_gray, gray)
            _, thresh = cv2.threshold(diff, DIFF_THRESHOLD, 255, cv2.THRESH_BINARY)

            motion = cv2.countNonZero(thresh)
            t_sec = frame_count / fps

            # If frame motion exceeds threshold, detect candidate objects
            if motion > MOTION_THRESHOLD:
                if TARGET_OBJECT == 'person' and hog is not None:
                    crop_resized = cv2.resize(crop, (800, int(crop.shape[0] * (800 / crop.shape[1]))))
                    rects, weights = hog.detectMultiScale(crop_resized, winStride=(8, 8), padding=(8, 8), scale=1.08)

                    for (rx, ry, rw, rh), weight in zip(rects, weights):
                        if weight >= MIN_CONFIDENCE and rh >= MIN_PERSON_HEIGHT:
                            scale_x = crop.shape[1] / 800.0
                            scale_y = crop.shape[0] / float(crop_resized.shape[0])
                            bx, by, bw, bh = (int(rx * scale_x), int(ry * scale_y), int(rw * scale_x), int(rh * scale_y))
                            cx = bx + bw / 2.0
                            cy = by + bh / 2.0

                            frame_candidates.append({
                                'time': t_sec,
                                'frame': frame.copy(),
                                'roi': roi_coords,
                                'bbox': (bx, by, bw, bh),
                                'center': (cx, cy),
                                'weight': float(weight),
                                'height': rh,
                                'motion': motion,
                                'cam_count': curr_cam_count,
                                'cam_slot': curr_slot,
                                'cam_name': canonical_area
                            })
                            break
                else:
                    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    if contours:
                        c_max = max(contours, key=cv2.contourArea)
                        if cv2.contourArea(c_max) > 1000:
                            bx, by, bw, bh = cv2.boundingRect(c_max)
                            cx = bx + bw / 2.0
                            cy = by + bh / 2.0
                            frame_candidates.append({
                                'time': t_sec,
                                'frame': frame.copy(),
                                'roi': roi_coords,
                                'bbox': (bx, by, bw, bh),
                                'center': (cx, cy),
                                'weight': 1.0,
                                'height': bh,
                                'motion': motion,
                                'cam_count': curr_cam_count,
                                'cam_slot': curr_slot,
                                'cam_name': canonical_area
                            })

            prev_gray = gray
            prev_cam_count = curr_cam_count
            prev_slot = curr_slot

        cap.release()

        # Perform temporal multi-frame verification across at least 3 frames
        is_valid_event, three_frames, total_movement = verify_moving_event(frame_candidates, min_move_px=MIN_MOVEMENT_PX)

        if is_valid_event and three_frames:
            peak_motion = max(f['motion'] for f in three_frames)
            print(f"--> Confirmed MOVING {TARGET_OBJECT} in {vid} ({url}): moved {total_movement:.1f}px across 3 frames (Peak Motion: {peak_motion:,} px)")
            verified_video_events.append({
                'score': peak_motion,
                'movement': total_movement,
                'vid': vid,
                'url': url,
                'time_peak': three_frames[1]['time'],
                'three_frames': three_frames
            })
        elif frame_candidates:
            print(f"    Filtered static object in {vid}: {len(frame_candidates)} detections with only {total_movement:.1f}px movement (< {MIN_MOVEMENT_PX}px).")

        if (idx + 1) % 50 == 0:
            print(f"Processed {idx + 1} videos...")

    verified_video_events.sort(key=lambda x: (x['movement'] * 1000 + x['score']), reverse=True)

    snapshot_file = f"snapshot_{CHECK_AREA}.jpg"

    if verified_video_events:
        top_event = verified_video_events[0]
        annotate_and_save_group_snapshot(
            three_frames_data=top_event['three_frames'],
            area_name=CHECK_AREA,
            target_obj=TARGET_OBJECT,
            vid=top_event['vid'],
            url=top_event['url'],
            total_movement_px=top_event['movement'],
            output_path=snapshot_file
        )

    with open("report.txt", "a", encoding="utf-8") as f:
        f.write(f"=== Report for {CHECK_AREA} ({TARGET_OBJECT}) ===\n")
        if verified_video_events:
            top_event = verified_video_events[0]
            f.write(f"OBJECT FOUND!\n\n")
            f.write(f"Top video: {top_event['url']} at {top_event['time_peak']:.1f}s\n")
            f.write(f"Motion Score: {top_event['score']} pixels (Displacement: {top_event['movement']:.1f}px across 3 frames)\n")
            f.write(f"Screenshot: {snapshot_file}\n\n")
            f.write("Other top candidates:\n")
            for i in range(1, min(5, len(verified_video_events))):
                ev = verified_video_events[i]
                f.write(f"Rank {i+1}: {ev['url']} at {ev['time_peak']:.1f}s (Movement: {ev['movement']:.1f}px, Score: {ev['score']})\n")
        else:
            f.write("no find\n")
        f.write("\n")

    print("Report generated.")


if __name__ == "__main__":
    main()
