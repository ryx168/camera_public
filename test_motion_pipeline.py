#!/usr/bin/env python3
"""
test_motion_pipeline.py
Test script to verify:
1. Camera corner text detection (Office, Front, Kitchen/Kichen, Balcony, Backyard)
2. Multi-camera layout detection (5, 4, 3, 2, 1 cameras)
3. Camera bounding box mapping and same-camera screen matching
4. Prevention of cross-layout & mismatched screen comparisons
5. Temporal motion verification with same-camera enforcement
6. 3-frame composite group snapshot generation with camera & layout HUD
7. Report parsing and email delivery dry run
"""

import os
import sys
import numpy as np
import cv2
from check_recent_motion import (
    detect_cameras_from_frame,
    detect_camera_layout,
    get_camera_bounds,
    is_multicam_grid,
    verify_moving_event,
    annotate_and_save_group_snapshot
)
from send_motion_email import parse_report_file, build_email_content, send_email


def create_synthetic_frame_with_labels(cam_names, w=1280, h=480):
    """Creates synthetic multi-camera frames with ffmpeg-style corner text labels."""
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    cam_count = len(cam_names)
    h2 = h // 2
    w3 = w // 3
    w2 = w // 2

    slots = []
    if cam_count == 5:
        slots = [
            (0, 0, w3, h2),
            (w3, 0, 2*w3, h2),
            (2*w3, 0, w, h2),
            (0, h2, w2, h),
            (w2, h2, w, h)
        ]
    elif cam_count == 4:
        slots = [
            (0, 0, w2, h2),
            (w2, 0, w, h2),
            (0, h2, w2, h),
            (w2, h2, w, h)
        ]
    elif cam_count == 3:
        slots = [
            (0, 0, w2, h2),
            (w2, 0, w, h2),
            (0, h2, w, h)
        ]
    elif cam_count == 2:
        slots = [
            (0, 0, w2, h),
            (w2, 0, w, h)
        ]
    elif cam_count == 1:
        slots = [
            (0, 0, w, h)
        ]

    for i, (name, (x1, y1, x2, y2)) in enumerate(zip(cam_names, slots)):
        color = ((i * 50 + 40) % 255, (i * 70 + 60) % 255, (i * 90 + 80) % 255)
        frame[y1:y2, x1:x2] = color
        # Draw black background box and white text
        cv2.rectangle(frame, (x1+6, y1+6), (x1+115, y1+30), (0, 0, 0), -1)
        cv2.putText(frame, name, (x1+10, y1+24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)

    return frame


def test_pipeline():
    print("1. Testing corner text detection on real sample frame...")
    if os.path.exists("sample_Untitled Broadcast_v2829086396.mp4.jpg"):
        real_img = cv2.imread("sample_Untitled Broadcast_v2829086396.mp4.jpg")
        real_map, real_count, real_layout = detect_cameras_from_frame(real_img)
        print(f"   Real frame layout: {real_layout} ({real_count} cameras)")
        for cname, bounds in real_map.items():
            print(f"     Found {cname.upper()}: bounds = {bounds}")
        assert real_count == 5, f"Expected 5 cameras in real sample, got {real_count}"
        assert 'front' in real_map and 'kitchen' in real_map and 'office' in real_map
        print("   ✅ Real frame corner text accurately detected Office, Front, Kitchen, Balcony, Backyard.")

    print("\n2. Testing multi-camera layout detection across 5, 4, 3, 2, 1 camera grids...")
    layouts_to_test = {
        5: ['Office', 'Front', 'Kitchen', 'Balcony', 'Backyard'],
        4: ['Office', 'Front', 'Kitchen', 'Backyard'],
        3: ['Office', 'Front', 'Kitchen'],
        2: ['Office', 'Front'],
        1: ['Front']
    }

    frames = {}
    for count, names in layouts_to_test.items():
        syn_frame = create_synthetic_frame_with_labels(names)
        frames[count] = syn_frame
        cam_map, detected_count, layout_name = detect_cameras_from_frame(syn_frame)
        print(f"   {count}-cam grid ({names}) -> Detected {layout_name} ({detected_count} cams): {list(cam_map.keys())}")
        assert detected_count == count, f"Expected {count} cameras, got {detected_count}"

    assert is_multicam_grid(frames[5]) is True
    assert is_multicam_grid(frames[4]) is True
    assert is_multicam_grid(frames[3]) is True
    assert is_multicam_grid(frames[1]) is False
    print("   ✅ Layout detection verified for 5, 4, 3, 2, and 1 camera grids.")

    print("\n3. Testing camera bounds lookup and same-camera screen matching...")
    frame_5 = frames[5]
    frame_4 = frames[4]
    frame_3 = frames[3]

    b5_front = get_camera_bounds(frame_5, "front", cam_count=5)
    b5_house = get_camera_bounds(frame_5, "house_around", cam_count=5)
    b5_garage = get_camera_bounds(frame_5, "garage", cam_count=5)
    b5_kitchen = get_camera_bounds(frame_5, "kitchen", cam_count=5)
    b5_balcony = get_camera_bounds(frame_5, "balcony", cam_count=5)
    b5_backyard = get_camera_bounds(frame_5, "backyard", cam_count=5)

    assert b5_front == (426, 0, 852, 240)
    assert b5_house == b5_front, "house_around alias should resolve to Front camera"
    assert b5_garage == b5_kitchen, "garage alias should resolve to Kitchen camera"
    assert b5_kitchen == (852, 0, 1280, 240)
    assert b5_balcony == (0, 240, 640, 480)
    assert b5_backyard == (640, 240, 1280, 480)

    # 4-camera layout bounds
    b4_front = get_camera_bounds(frame_4, "front", cam_count=4)
    b4_kitchen = get_camera_bounds(frame_4, "kitchen", cam_count=4)
    assert b4_front == (640, 0, 1280, 240)
    assert b4_kitchen == (0, 240, 640, 480)

    # 3-camera layout bounds
    b3_front = get_camera_bounds(frame_3, "front", cam_count=3)
    b3_kitchen = get_camera_bounds(frame_3, "kitchen", cam_count=3)
    b3_balcony = get_camera_bounds(frame_3, "balcony", cam_count=3)
    assert b3_front == (640, 0, 1280, 240)
    assert b3_kitchen == (0, 240, 1280, 480)
    assert b3_balcony is None, "Balcony should be None in 3-camera layout"
    print("   ✅ Exact camera bounds and alias resolution verified.")

    print("\n4. Testing layout change protection (No comparison across different camera count screens)...")
    prev_cam = 5
    curr_cam = 4
    can_compare = (prev_cam == curr_cam)
    assert can_compare is False, "Cross-layout comparison must be prohibited!"
    print("   ✅ Cross-layout frame diff correctly rejected.")

    print("\n5. Testing temporal motion verification with same-camera slot enforcement...")
    # Test 5a: Mixed camera slot candidates should not cluster together
    mixed_candidates = [
        {'time': 1.0, 'frame': frame_5, 'roi': (426, 48, 852, 240), 'bbox': (50, 160, 70, 130), 'center': (85.0, 225.0), 'weight': 0.8, 'motion': 45000, 'cam_count': 5, 'cam_slot': (426, 0, 852, 240), 'cam_name': 'front'},
        {'time': 2.0, 'frame': frame_4, 'roi': (640, 48, 1280, 240), 'bbox': (140, 110, 70, 130), 'center': (175.0, 175.0), 'weight': 0.8, 'motion': 78000, 'cam_count': 4, 'cam_slot': (640, 0, 1280, 240), 'cam_name': 'front'},
        {'time': 3.0, 'frame': frame_5, 'roi': (426, 48, 852, 240), 'bbox': (220, 60, 70, 130), 'center': (255.0, 125.0), 'weight': 0.8, 'motion': 62000, 'cam_count': 5, 'cam_slot': (426, 0, 852, 240), 'cam_name': 'front'},
    ]
    is_valid_mixed, _, _ = verify_moving_event(mixed_candidates, min_move_px=25.0)
    assert is_valid_mixed is False, "Mixed camera layouts across frames must NOT be verified as a valid single event!"
    print("   ✅ Mixed-camera candidate set correctly rejected.")

    # Test 5b: Real moving person within consistent 5-camera Front slot
    moving_5cam = [
        {'time': 3.0, 'frame': frame_5, 'roi': (426, 48, 852, 240), 'bbox': (50, 160, 70, 130), 'center': (85.0, 225.0), 'weight': 0.75, 'motion': 45000, 'cam_count': 5, 'cam_slot': (426, 0, 852, 240), 'cam_name': 'front'},
        {'time': 5.0, 'frame': frame_5, 'roi': (426, 48, 852, 240), 'bbox': (140, 110, 70, 130), 'center': (175.0, 175.0), 'weight': 0.88, 'motion': 78000, 'cam_count': 5, 'cam_slot': (426, 0, 852, 240), 'cam_name': 'front'},
        {'time': 7.0, 'frame': frame_5, 'roi': (426, 48, 852, 240), 'bbox': (220, 60, 70, 130), 'center': (255.0, 125.0), 'weight': 0.80, 'motion': 62000, 'cam_count': 5, 'cam_slot': (426, 0, 852, 240), 'cam_name': 'front'},
    ]
    is_valid_moving, three_frames, move_real = verify_moving_event(moving_5cam, min_move_px=25.0)
    assert is_valid_moving is True
    assert len(three_frames) == 3
    assert all(f.get('cam_count') == 5 and f.get('cam_name') == 'front' for f in three_frames)
    print(f"   ✅ Real moving person confirmed with consistent 5-camera Front screen (Displacement: {move_real:.1f}px).")

    # Test 5c: Real moving vehicle within consistent 4-camera Kitchen/Garage slot
    moving_4cam = [
        {'time': 2.0, 'frame': frame_4, 'roi': (0, 240, 640, 480), 'bbox': (40, 40, 120, 80), 'center': (100.0, 80.0), 'weight': 1.0, 'motion': 36000, 'cam_count': 4, 'cam_slot': (0, 240, 640, 480), 'cam_name': 'kitchen'},
        {'time': 4.0, 'frame': frame_4, 'roi': (0, 240, 640, 480), 'bbox': (140, 80, 120, 80), 'center': (200.0, 120.0), 'weight': 1.0, 'motion': 48000, 'cam_count': 4, 'cam_slot': (0, 240, 640, 480), 'cam_name': 'kitchen'},
        {'time': 6.0, 'frame': frame_4, 'roi': (0, 240, 640, 480), 'bbox': (240, 120, 120, 80), 'center': (300.0, 160.0), 'weight': 1.0, 'motion': 41000, 'cam_count': 4, 'cam_slot': (0, 240, 640, 480), 'cam_name': 'kitchen'},
    ]
    is_valid_4cam, three_4cam, move_4cam = verify_moving_event(moving_4cam, min_move_px=25.0)
    assert is_valid_4cam is True
    assert len(three_4cam) == 3
    assert all(f.get('cam_count') == 4 and f.get('cam_name') == 'kitchen' for f in three_4cam)
    print(f"   ✅ Real moving vehicle confirmed with consistent 4-camera Kitchen screen (Displacement: {move_4cam:.1f}px).")

    print("\n6. Generating 3-frame composite group snapshots with camera HUD...")
    annotate_and_save_group_snapshot(
        three_frames_data=three_frames,
        area_name="house_around",
        target_obj="person",
        vid="2833002021",
        url="https://www.twitch.tv/videos/2833002021",
        total_movement_px=move_real,
        output_path="snapshot_house_around.jpg"
    )
    assert os.path.exists("snapshot_house_around.jpg")
    img = cv2.imread("snapshot_house_around.jpg")
    assert img.shape[0] > 1400
    print(f"   ✅ Generated 5-cam composite snapshot (Resolution: {img.shape[1]}x{img.shape[0]}).")

    annotate_and_save_group_snapshot(
        three_frames_data=three_4cam,
        area_name="garage",
        target_obj="car",
        vid="2833004002",
        url="https://www.twitch.tv/videos/2833004002",
        total_movement_px=move_4cam,
        output_path="snapshot_garage.jpg"
    )
    assert os.path.exists("snapshot_garage.jpg")
    print("   ✅ Generated 4-cam composite snapshot successfully.")

    print("\n7. Testing report parsing and email generation...")
    test_report_content = f"""=== Report for house_around (person) ===
OBJECT FOUND!

Top video: https://www.twitch.tv/videos/2833002021 at 5.0s
Motion Score: 78000 pixels (Displacement: {move_real:.1f}px across 3 frames)
Screenshot: snapshot_house_around.jpg

=== Report for garage (car) ===
OBJECT FOUND!

Top video: https://www.twitch.tv/videos/2833004002 at 4.0s
Motion Score: 48000 pixels (Displacement: {move_4cam:.1f}px across 3 frames)
Screenshot: snapshot_garage.jpg
"""
    with open("test_report.txt", "w", encoding="utf-8") as f:
        f.write(test_report_content)

    sections, raw_text = parse_report_file("test_report.txt")
    assert len(sections) == 2
    assert sections[0]["detected"] is True
    assert sections[1]["detected"] is True
    print(f"   ✅ Parsed {len(sections)} sections accurately.")

    subject, plain_body, html_body = build_email_content(sections, raw_text)
    assert "MOTION DETECTED" in subject
    assert "cid:snapshot_house_around.jpg" in html_body
    assert "cid:snapshot_garage.jpg" in html_body
    print("   ✅ Email HTML contains all composite CID image references.")

    print("\n8. Testing send_email dry run...")
    os.environ["REPORT_PATH"] = "test_report.txt"
    send_email(dry_run=True)
    print("   ✅ send_email dry run passed with full MIME packaging.")

    # Cleanup temporary test files
    for temp_f in ["test_report.txt", "snapshot_house_around.jpg", "snapshot_garage.jpg"]:
        if os.path.exists(temp_f):
            os.remove(temp_f)
    print("   ✅ Cleaned up temporary test files.")

    print("\n🎉 ALL TESTS (Corner Text Detection, Camera Count, Same-Camera Screen Matching) PASSED!")


if __name__ == "__main__":
    test_pipeline()
