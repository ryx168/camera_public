#!/usr/bin/env python3
"""
check_recent_motion.py
Scans recent Twitch VODs for motion and person/car activity.
Detects camera count and layout by reading corner text labels ('Office', 'Front', 'Kitchen'/'Kichen', 'Balcony', 'Backyard').
Matches the same camera screen across frames and rejects cross-layout comparisons.
Performs temporal multi-frame motion verification across at least 3 frames to reject
static false positives (railings, tree trunks, gates, posts) and saves 3 separate
(START/PEAK/END) annotated screenshots illustrating object displacement over time,
all limited to videos from the last LOOKBACK_HOURS (default 3) hours.
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


def get_pacific_time(dt=None, epoch=None):
    """
    Get datetime in US Pacific timezone (America/Los_Angeles).
    Supports converting an existing datetime object or epoch timestamp to Pacific Time.
    If neither is passed, returns the current Pacific datetime.
    Accurately handles Daylight Saving Time (PDT, UTC-7) vs Standard Time (PST, UTC-8)
    across Python 3.9+ (zoneinfo), python-dateutil, and dynamic UTC-offset fallback.
    """
    if epoch is not None:
        target_utc = datetime.datetime.fromtimestamp(epoch, tz=timezone.utc)
    elif dt is not None:
        if dt.tzinfo is None:
            target_utc = dt.replace(tzinfo=timezone.utc)
        else:
            target_utc = dt.astimezone(timezone.utc)
    else:
        target_utc = datetime.datetime.now(timezone.utc)

    try:
        from zoneinfo import ZoneInfo
        return target_utc.astimezone(ZoneInfo("America/Los_Angeles"))
    except Exception:
        pass

    try:
        import dateutil.tz
        tz = dateutil.tz.gettz("America/Los_Angeles")
        if tz:
            return target_utc.astimezone(tz)
    except Exception:
        pass

    # Dynamic US Pacific DST calculation:
    # DST begins 2nd Sunday in March at 2:00 AM PST (10:00 UTC)
    # DST ends 1st Sunday in November at 2:00 AM PDT (9:00 UTC)
    year = target_utc.year
    mar1 = datetime.datetime(year, 3, 1, tzinfo=timezone.utc)
    dst_start = mar1 + datetime.timedelta(days=(6 - mar1.weekday() + 7) % 7 + 7, hours=10)
    nov1 = datetime.datetime(year, 11, 1, tzinfo=timezone.utc)
    dst_end = nov1 + datetime.timedelta(days=(6 - nov1.weekday()) % 7, hours=9)

    if dst_start <= target_utc < dst_end:
        tz_offset = datetime.timezone(datetime.timedelta(hours=-7), name="PDT")
    else:
        tz_offset = datetime.timezone(datetime.timedelta(hours=-8), name="PST")

    return target_utc.astimezone(tz_offset)

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
    'backyard': ['backyard', 'back', 'yard', 'ackyard', 'kyard'],
    'basement': ['basement', 'base', 'ement', 'asement', 'sement']
}

# Alias mapping from check_area / env vars to canonical camera names
ALIAS_TO_CANONICAL = {
    'office': 'office', 'cam1': 'office',
    'front': 'front', 'cam2': 'front', 'house_around': 'front', 'door': 'front', 'house': 'front',
    'kitchen': 'kitchen', 'kichen': 'kitchen', 'garage': 'kitchen', 'cam3': 'kitchen', 'car': 'kitchen', 'driveway': 'kitchen',
    'balcony': 'balcony', 'cam4': 'balcony',
    'backyard': 'backyard', 'cam5': 'backyard', 'yard': 'backyard',
    'basement': 'basement', 'cam6': 'basement', 'wyze': 'basement'
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
        6: [
            ('top_left', (0, 0, w3, h2)),
            ('top_mid', (w3, 0, 2*w3, h2)),
            ('top_right', (2*w3, 0, w, h2)),
            ('bot_left', (0, h2, w3, h)),
            ('bot_mid', (w3, h2, 2*w3, h)),
            ('bot_right', (2*w3, h2, w, h)),
        ],
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
    for num_cams in [6, 5, 4, 3, 2, 1]:
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
    return layout in [6, 5, 4, 3]


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

    if cam_count == 6:
        # 3x2 grid, matching build_filter_complex case 6) in start-stream.sh
        w3 = w // 3
        h2 = h // 2
        slots6 = {
            'office': (0, 0, w3, h2), 'front': (w3, 0, 2*w3, h2), 'kitchen': (2*w3, 0, w, h2),
            'balcony': (0, h2, w3, h), 'backyard': (w3, h2, 2*w3, h), 'basement': (2*w3, h2, w, h),
        }
        return slots6.get(canonical)

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


def annotate_and_save_snapshots(three_frames_data, area_name, target_obj, vid, url, total_movement_px, output_prefix, vod_epoch=None):
    """
    Saves 3 SEPARATE annotated screenshot images (START, PEAK, END) - one per
    verified detection frame - instead of a single stacked composite. Each frame
    is labeled with its own HUD header showing camera, target, timestamp (in Pacific Time) and
    displacement info so the email can show all three near the detection time.

    Returns a list of dicts: [{'path':..., 'time':..., 'phase':...}, ...] in
    START -> PEAK -> END order.
    """
    out_dir = os.path.dirname(os.path.abspath(output_prefix))
    os.makedirs(out_dir, exist_ok=True)

    now_pac = get_pacific_time()
    tz_abbr = now_pac.strftime("%Z") or "PDT"
    now_time_str = now_pac.strftime(f"%Y-%m-%d %I:%M:%S %p {tz_abbr}")
    phase_suffix_map = {'START': 'start', 'PEAK': 'peak', 'END': 'end'}
    saved = []

    for idx, item in enumerate(three_frames_data):
        phase = item.get('phase', f'FRAME {idx+1}')
        try:
            frame = item['frame'].copy()
            h, w = frame.shape[:2]
            crop_roi = item['roi']
            bbox = item['bbox']
            t_sec = item['time']
            conf = item.get('weight', 1.0)
            cx, cy = item.get('center', (0, 0))
            motion_px = item.get('motion', 0)
            cam_name = item.get('cam_name', area_name)
            cam_count = item.get('cam_count', 5)

            # Format frame detection time in Pacific Time (PST/PDT)
            vod_time_info = ""
            if vod_epoch:
                f_pac = get_pacific_time(epoch=vod_epoch + t_sec)
                f_tz = f_pac.strftime("%Z") or "PDT"
                vod_time_info = f" | {f_pac.strftime('%I:%M:%S %p')} {f_tz}"

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

            # 3. HUD header bar (2 lines) on this individual frame
            header_h = 54
            overlay = frame.copy()
            cv2.rectangle(overlay, (0, 0), (w, header_h), (12, 12, 22), -1)
            cv2.addWeighted(overlay, 0.80, frame, 0.20, 0, frame)
            cv2.line(frame, (0, header_h), (w, header_h), (0, 160, 255), 2)

            line1 = f"[{phase}] {cam_name.upper()} | Target: {target_obj.upper()} | Layout: {cam_count}-Cam | Frame {idx+1}/3"
            cv2.putText(frame, line1, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 235, 255), 1, cv2.LINE_AA)

            line2 = f"VOD {vid} @ {t_sec:.1f}s{vod_time_info} | Motion: {motion_px:,}px | Move: {total_movement_px:.1f}px | Check: {now_time_str}"
            cv2.putText(frame, line2, (10, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (220, 220, 220), 1, cv2.LINE_AA)

            suffix = phase_suffix_map.get(phase, f"f{idx+1}")
            out_path = f"{output_prefix}_{suffix}.jpg"
            ok = cv2.imwrite(out_path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            if ok and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                saved.append({'path': out_path, 'time': t_sec, 'phase': phase})
                print(f"Saved snapshot [{phase}] at {t_sec:.1f}s to: {out_path} ({os.path.getsize(out_path)} bytes)")
            else:
                print(f"WARNING: cv2.imwrite reported failure for [{phase}] frame -> {out_path}")
        except Exception as e:
            # Never let one bad frame wipe out the other verified screenshots
            print(f"WARNING: Failed to annotate/save [{phase}] frame ({idx+1}/3): {e}")
            continue

    print(f"annotate_and_save_snapshots: {len(saved)}/3 screenshots saved successfully for prefix '{output_prefix}'")
    return saved


# Suppress noisy OpenCV / FFmpeg stderr warnings and configure timeouts
os.environ["OPENCV_LOG_LEVEL"] = "ERROR"
os.environ["OPENCV_FFMPEG_READ_ATTEMPTS"] = "2"
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "timeout;5000000|analyzeduration;5000000|probesize;5000000"

try:
    if hasattr(cv2, 'setLogLevel'):
        cv2.setLogLevel(0)
    elif hasattr(cv2, 'utils') and hasattr(cv2.utils, 'logging'):
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except Exception:
    pass


def prepare_local_vod(vid, temp_dir="temp_vods"):
    """
    Downloads or retrieves the local cached MP4 for a Twitch VOD.
    Using local MP4 files prevents OpenCV cap_ffmpeg interrupt callback timeouts (30s per EOF)
    and HTTP EOF decoding errors.
    Returns: (vid, web_url, local_path_or_stream_url)
    """
    url = f'https://www.twitch.tv/videos/{vid[1:]}'
    os.makedirs(temp_dir, exist_ok=True)
    local_path = os.path.join(temp_dir, f"{vid}.mp4")

    # If file already exists and is valid (> 10 KB), reuse it immediately
    if os.path.exists(local_path) and os.path.getsize(local_path) > 10240:
        return vid, url, local_path

    # Step 1: Get stream m3u8 URL from yt-dlp
    stream_url = ""
    try:
        res = subprocess.run(
            [sys.executable, '-m', 'yt_dlp', '-g', url],
            capture_output=True, text=True, timeout=20
        )
        stream_url = res.stdout.strip()
    except Exception:
        stream_url = ""

    if not stream_url:
        return vid, url, None

    # Step 2: Download HLS stream directly to MP4 using ffmpeg in stream-copy mode
    # Fast (<0.5s for 2MB clip), handles HLS chunks cleanly, and exits immediately at EOF
    temp_download = os.path.join(temp_dir, f"{vid}.downloading.mp4")
    try:
        ff_cmd = [
            'ffmpeg', '-y', '-nostdin', '-loglevel', 'error',
            '-rw_timeout', '15000000', '-timeout', '15000000',
            '-i', stream_url,
            '-c', 'copy',
            '-bsf:a', 'aac_adtstoasc',
            '-movflags', '+faststart',
            temp_download
        ]
        ff_res = subprocess.run(ff_cmd, capture_output=True, text=True, timeout=60)
        # We DO NOT check ff_res.returncode == 0 because ffmpeg often returns an error (e.g. 1) 
        # when an HLS stream ends abruptly without a clean endlist tag.
        if os.path.exists(temp_download) and os.path.getsize(temp_download) > 10240:
            if os.path.exists(local_path):
                try: os.remove(local_path)
                except Exception: pass
            os.rename(temp_download, local_path)
            return vid, url, local_path
    except Exception:
        pass
    finally:
        if os.path.exists(temp_download):
            try: os.remove(temp_download)
            except Exception: pass

    # Step 3: Fallback download via yt-dlp
    try:
        ytdl_cmd = [
            sys.executable, '-m', 'yt_dlp',
            '--no-playlist', '--no-warnings', '-q',
            '--concurrent-fragments', '4',
            '-f', 'best',
            '-o', local_path,
            url
        ]
        subprocess.run(ytdl_cmd, capture_output=True, timeout=120)
        if os.path.exists(local_path) and os.path.getsize(local_path) > 10240:
            return vid, url, local_path
    except Exception:
        pass

    # CRITICAL: Do NOT return stream_url! If local download completely fails, 
    # we must return None to skip this video. Passing stream_url to OpenCV 
    # guarantees a 30s timeout hang due to OpenCV's internal FFmpeg interrupt callback.
    return vid, url, None


def fetch_recent_videos(lookback_hours=3.0, cache_dir="temp_vods"):
    """
    Fetches recent videos metadata from Twitch with local disk caching
    to avoid redundant queries across multiple workflow steps.
    """
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, "metadata_cache.json")
    now_utc = datetime.datetime.now(timezone.utc)
    now_ts = now_utc.timestamp()
    now_pac = get_pacific_time(dt=now_utc)
    now_pac_str = now_pac.strftime(f"%Y-%m-%d %I:%M:%S %p {now_pac.strftime('%Z') or 'PDT'}")

    videos = []
    # Check if cache exists and is fresh (< 15 minutes old)
    if os.path.exists(cache_file):
        try:
            mtime = os.path.getmtime(cache_file)
            if (now_ts - mtime) < 900:
                with open(cache_file, "r", encoding="utf-8") as f:
                    videos = json.load(f)
                print(f"Loaded {len(videos)} video metadata entries from local cache.")
        except Exception:
            videos = []

    if not videos:
        print(f"Fetching recent videos metadata from Twitch (as of {now_pac_str})...")
        res = subprocess.run([
            sys.executable, '-m', 'yt_dlp',
            '--flat-playlist', '--dump-json', '--playlist-items', '1-400',
            'https://www.twitch.tv/elarathornfield168/videos?filter=all&sort=time'
        ], capture_output=True, text=True)

        lines = res.stdout.strip().split('\n')
        if not lines or lines[0] == '':
            print("Failed to fetch videos")
            if res.stderr:
                print("yt_dlp stderr:", res.stderr)
            return []

        for l in lines:
            try:
                videos.append(json.loads(l))
            except Exception:
                pass

        if videos:
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(videos, f)
            except Exception:
                pass

    target_epoch = now_ts - (lookback_hours * 3600)
    start_pac = get_pacific_time(epoch=target_epoch)
    start_pac_str = start_pac.strftime(f"%Y-%m-%d %I:%M:%S %p {start_pac.strftime('%Z') or 'PDT'}")
    print(f"Scan window (Pacific Time): {start_pac_str} to {now_pac_str} ({lookback_hours:.1f} hours)")

    recent_videos = []
    for v in videos:
        # Extract true broadcast epoch from Twitch thumbnail URL:
        # e.g., "..._elarathornfield168_318630196567_1785176728//thumb/thumb0-320x180.jpg"
        epoch = None
        thumb = v.get('thumbnail') or ''
        m = re.search(r'_(\d{9,11})//?thumb', thumb)
        if m:
            epoch = int(m.group(1))
        elif v.get('timestamp'):
            epoch = int(v['timestamp'])
        elif v.get('release_timestamp'):
            epoch = int(v['release_timestamp'])

        if epoch and epoch >= target_epoch:
            v['epoch'] = epoch
            recent_videos.append(v)

    return recent_videos


def main():
    lookback_hours = float(os.environ.get('LOOKBACK_HOURS', '3.0'))
    recent_videos = fetch_recent_videos(lookback_hours=lookback_hours)

    now_pac = get_pacific_time()
    tz_abbr = now_pac.strftime("%Z") or "PDT"
    now_pac_str = now_pac.strftime(f"%Y-%m-%d %I:%M:%S %p {tz_abbr}")

    if not recent_videos:
        print(f"No videos found in the last {lookback_hours:.1f} hours ({now_pac_str}). Exiting.")
        with open("report.txt", "a", encoding="utf-8") as f:
            f.write(f"=== Report for {CHECK_AREA} ({TARGET_OBJECT}) ===\n")
            f.write(f"Check Time (Pacific): {now_pac_str}\n")
            f.write("Status: NO_FOOTAGE\n")
            f.write(f"Window: last {lookback_hours:.1f} hours\n")
            f.write("Videos scanned: 0\n")
            f.write(f"no videos in the last {lookback_hours:.1f} hours\n\n")
        exit(0)

    print(f"Found {len(recent_videos)} videos in the last {lookback_hours:.1f} hours (Checked at {now_pac_str})")
    ids = [v['id'] for v in recent_videos]
    vid_epoch_map = {v['id']: v.get('epoch') for v in recent_videos}

    print("Fetching and preparing VOD sources in parallel...")
    vod_sources = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(prepare_local_vod, ids[i]): ids[i] for i in range(len(ids))}
        for i, future in enumerate(as_completed(futures)):
            vid, url, vod_source = future.result()
            if vod_source:
                vod_sources[vid] = (url, vod_source)
            if (i+1) % 25 == 0 or (i+1) == len(ids):
                print(f"Prepared {i+1}/{len(ids)} VODs...")

    canonical_area = ALIAS_TO_CANONICAL.get(CHECK_AREA, CHECK_AREA)
    print(f"Got {len(vod_sources)} ready video sources. Starting motion & temporal tracking for camera '{canonical_area}' (alias '{CHECK_AREA}')...")

    # Region of Interest (ROI) within selected camera bounds
    default_roi_y_min = '0.20' if canonical_area in ['front', 'kitchen'] else '0.0'
    ROI_Y_MIN = float(os.environ.get('ROI_Y_MIN', default_roi_y_min))
    ROI_Y_MAX = float(os.environ.get('ROI_Y_MAX', '1.0'))
    ROI_X_MIN = float(os.environ.get('ROI_X_MIN', '0.0'))
    ROI_X_MAX = float(os.environ.get('ROI_X_MAX', '1.0'))

    default_diff_th = '30' if (TARGET_OBJECT == 'car' or canonical_area == 'kitchen') else '35'
    default_motion_th = '2500' if (TARGET_OBJECT == 'car' or canonical_area == 'kitchen') else '25000'
    default_min_move = '15.0' if (TARGET_OBJECT == 'car' or canonical_area == 'kitchen') else '25.0'

    DIFF_THRESHOLD = int(os.environ.get('DIFF_THRESHOLD', default_diff_th))
    MOTION_THRESHOLD = int(os.environ.get('MOTION_THRESHOLD', default_motion_th))
    MIN_PERSON_HEIGHT = int(os.environ.get('MIN_PERSON_HEIGHT', '100'))
    MIN_CONFIDENCE = float(os.environ.get('MIN_CONFIDENCE', '0.60'))
    MIN_MOVEMENT_PX = float(os.environ.get('MIN_MOVEMENT_PX', default_min_move))

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
        if vid not in vod_sources: continue
        url, video_source = vod_sources[vid]

        cap = cv2.VideoCapture(video_source)
        if not cap.isOpened():
            cap.release()
            continue

        ret, prev_frame = cap.read()
        if not ret:
            cap.release()
            continue

        # Step 1: Detect initial camera layout and matching camera corner text
        init_cam_map, init_cam_count, init_layout = detect_cameras_from_frame(prev_frame)
        if init_cam_count not in [6, 5, 4, 3, 2, 1]:
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
            if curr_cam_count not in [6, 5, 4, 3, 2, 1]:
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
                'epoch': vid_epoch_map.get(vid),
                'time_peak': three_frames[1]['time'],
                'three_frames': three_frames
            })
        elif frame_candidates:
            print(f"    Filtered static object in {vid}: {len(frame_candidates)} detections with only {total_movement:.1f}px movement (< {MIN_MOVEMENT_PX}px).")

        if (idx + 1) % 50 == 0 or (idx + 1) == len(ids):
            print(f"Processed {idx + 1}/{len(ids)} videos...")

    verified_video_events.sort(key=lambda x: (x['movement'] * 1000 + x['score']), reverse=True)

    snapshot_prefix = f"snapshot_{CHECK_AREA}"
    saved_snapshots = []

    if verified_video_events:
        top_event = verified_video_events[0]
        try:
            saved_snapshots = annotate_and_save_snapshots(
                three_frames_data=top_event['three_frames'],
                area_name=CHECK_AREA,
                target_obj=TARGET_OBJECT,
                vid=top_event['vid'],
                url=top_event['url'],
                total_movement_px=top_event['movement'],
                output_prefix=snapshot_prefix,
                vod_epoch=top_event.get('epoch')
            )
        except Exception as e:
            # Never let a snapshot-rendering failure prevent report.txt from being
            # written - the email should still report the detection, just without images.
            print(f"ERROR: annotate_and_save_snapshots failed entirely: {e}")
            saved_snapshots = []

    with open("report.txt", "a", encoding="utf-8") as f:
        f.write(f"=== Report for {CHECK_AREA} ({TARGET_OBJECT}) ===\n")
        f.write(f"Check Time (Pacific): {now_pac_str}\n")
        f.write("Status: FOUND\n" if verified_video_events else "Status: CLEAR\n")
        f.write(f"Window: last {lookback_hours:.1f} hours\n")
        f.write(f"Videos scanned: {len(recent_videos)}\n")
        _eps = [v.get("epoch") for v in recent_videos if v.get("epoch")]
        if _eps:
            _c0 = get_pacific_time(epoch=min(_eps)).strftime("%I:%M %p")
            _c1 = get_pacific_time(epoch=max(_eps))
            _tz = _c1.strftime("%Z") or "PDT"
            f.write(f"Footage covers: {_c0} - {_c1.strftime('%I:%M %p')} {_tz}\n")
        if verified_video_events:
            top_event = verified_video_events[0]
            vod_epoch = top_event.get('epoch')
            if vod_epoch:
                ev_pac = get_pacific_time(epoch=vod_epoch + top_event['time_peak'])
                ev_str = ev_pac.strftime(f"%Y-%m-%d %I:%M:%S %p {ev_pac.strftime('%Z') or 'PDT'}")
                f.write(f"OBJECT FOUND!\n\n")
                f.write(f"Detection Time (Pacific): {ev_str}\n")
                f.write(f"Top video: {top_event['url']} at {top_event['time_peak']:.1f}s ({ev_str})\n")
            else:
                f.write(f"OBJECT FOUND!\n\n")
                f.write(f"Top video: {top_event['url']} at {top_event['time_peak']:.1f}s\n")
            f.write(f"Motion Score: {top_event['score']} pixels (Displacement: {top_event['movement']:.1f}px across 3 frames)\n")
            for s in saved_snapshots:
                f.write(f"Screenshot [{s['phase']}] at {s['time']:.1f}s: {s['path']}\n")
            f.write("\n")
            f.write("Other top candidates:\n")
            for i in range(1, min(5, len(verified_video_events))):
                ev = verified_video_events[i]
                ev_epoch = ev.get('epoch')
                if ev_epoch:
                    cand_pac = get_pacific_time(epoch=ev_epoch + ev['time_peak'])
                    cand_str = cand_pac.strftime(f"%I:%M:%S %p {cand_pac.strftime('%Z') or 'PDT'}")
                    f.write(f"Rank {i+1}: {ev['url']} at {ev['time_peak']:.1f}s ({cand_str}) (Movement: {ev['movement']:.1f}px, Score: {ev['score']})\n")
                else:
                    f.write(f"Rank {i+1}: {ev['url']} at {ev['time_peak']:.1f}s (Movement: {ev['movement']:.1f}px, Score: {ev['score']})\n")
        else:
            f.write("no find\n")
        f.write("\n")

    print("Report generated.")


if __name__ == "__main__":
    main()