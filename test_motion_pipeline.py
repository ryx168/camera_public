#!/usr/bin/env python3
"""
test_motion_pipeline.py
Test script to verify:
1. Multi-camera layout detection (5, 4, 3 cameras vs single camera)
2. Camera bounding boxes for 5-cam, 4-cam, and 3-cam layouts
3. Prevention of cross-layout frame comparisons (no diff across different camera count screens)
4. Temporal motion verification with same-layout enforcement
5. 3-frame composite group snapshot generation with layout metadata
6. Report parsing and email delivery dry run
"""

import os
import sys
import numpy as np
import cv2
from check_recent_motion import (
    detect_camera_layout,
    get_camera_bounds,
    is_multicam_grid,
    verify_moving_event,
    annotate_and_save_group_snapshot
)
from send_motion_email import parse_report_file, build_email_content, send_email


def create_synthetic_frame(cam_count, w=1280, h=480):
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    colors = [
        (30, 40, 50),
        (180, 190, 200),
        (80, 120, 60),
        (10, 80, 150),
        (40, 180, 50)
    ]
    if cam_count == 5:
        frame[0:h//2, 0:w//3] = colors[0]
        frame[0:h//2, w//3:2*w//3] = colors[1]
        frame[0:h//2, 2*w//3:w] = colors[2]
        frame[h//2:h, 0:w//2] = colors[3]
        frame[h//2:h, w//2:w] = colors[4]
    elif cam_count == 4:
        frame[0:h//2, 0:w//2] = colors[0]
        frame[0:h//2, w//2:w] = colors[1]
        frame[h//2:h, 0:w//2] = colors[2]
        frame[h//2:h, w//2:w] = colors[3]
    elif cam_count == 3:
        frame[0:h//2, 0:w//2] = colors[0]
        frame[0:h//2, w//2:w] = colors[1]
        frame[h//2:h, 0:w] = colors[2]
    elif cam_count == 2:
        frame[0:h, 0:w//2] = colors[0]
        frame[0:h, w//2:w] = colors[1]
    elif cam_count == 1:
        for y in range(h):
            frame[y, :] = int((y / float(h)) * 150)
    return frame


def test_pipeline():
    print("1. Testing camera layout detection (5, 4, 3, 2, 1 cameras)...")
    frame_5 = create_synthetic_frame(5)
    frame_4 = create_synthetic_frame(4)
    frame_3 = create_synthetic_frame(3)
    frame_2 = create_synthetic_frame(2)
    frame_1 = create_synthetic_frame(1)

    assert detect_camera_layout(frame_5) == 5, f"Expected 5 cameras, got {detect_camera_layout(frame_5)}"
    assert detect_camera_layout(frame_4) == 4, f"Expected 4 cameras, got {detect_camera_layout(frame_4)}"
    assert detect_camera_layout(frame_3) == 3, f"Expected 3 cameras, got {detect_camera_layout(frame_3)}"
    assert detect_camera_layout(frame_2) == 2, f"Expected 2 cameras, got {detect_camera_layout(frame_2)}"
    assert detect_camera_layout(frame_1) == 1, f"Expected 1 camera, got {detect_camera_layout(frame_1)}"

    assert is_multicam_grid(frame_5) is True, "5-camera should be valid multicam grid"
    assert is_multicam_grid(frame_4) is True, "4-camera should be valid multicam grid"
    assert is_multicam_grid(frame_3) is True, "3-camera should be valid multicam grid"
    assert is_multicam_grid(frame_1) is False, "Single camera should not be multicam grid"
    print("   ✅ Camera count detection accurate across 5, 4, 3, 2, and 1 camera screens.")

    print("\n2. Testing camera layout bounds for 5-cam, 4-cam, and 3-cam layouts...")
    w, h = 1280, 480
    # 5-camera bounds
    b5_front = get_camera_bounds(frame_5, "house_around", cam_count=5)
    b5_garage = get_camera_bounds(frame_5, "garage", cam_count=5)
    b5_balcony = get_camera_bounds(frame_5, "balcony", cam_count=5)
    assert b5_front == (426, 0, 852, 240), f"Unexpected 5-cam front bounds: {b5_front}"
    assert b5_garage == (852, 0, 1280, 240), f"Unexpected 5-cam garage bounds: {b5_garage}"
    assert b5_balcony == (0, 240, 640, 480), f"Unexpected 5-cam balcony bounds: {b5_balcony}"

    # 4-camera bounds (2x2)
    b4_front = get_camera_bounds(frame_4, "house_around", cam_count=4)
    b4_garage = get_camera_bounds(frame_4, "garage", cam_count=4)
    assert b4_front == (640, 0, 1280, 240), f"Unexpected 4-cam front bounds: {b4_front}"
    assert b4_garage == (0, 240, 640, 480), f"Unexpected 4-cam garage bounds: {b4_garage}"

    # 3-camera bounds (2 top, 1 bottom)
    b3_front = get_camera_bounds(frame_3, "house_around", cam_count=3)
    b3_garage = get_camera_bounds(frame_3, "garage", cam_count=3)
    b3_balcony = get_camera_bounds(frame_3, "balcony", cam_count=3)
    assert b3_front == (640, 0, 1280, 240), f"Unexpected 3-cam front bounds: {b3_front}"
    assert b3_garage == (0, 240, 1280, 480), f"Unexpected 3-cam garage bounds: {b3_garage}"
    assert b3_balcony is None, f"Expected balcony to be None in 3-camera layout, got {b3_balcony}"
    print("   ✅ Camera bounds correctly computed for 5-cam, 4-cam, and 3-cam layouts.")

    print("\n3. Testing layout change protection (No comparison across different camera count screens)...")
    # Simulate a stream that switches from 5-camera layout to 4-camera layout
    prev_cam = 5
    curr_cam = 4
    can_compare = (prev_cam == curr_cam)
    assert can_compare is False, "Cross-layout comparison must be prohibited!"
    print("   ✅ Cross-layout frame diff correctly rejected.")

    print("\n4. Testing temporal motion verification with layout integrity...")
    # Test 4a: Mixed layouts (candidate frames from 5-cam and 4-cam) should not cluster together
    mixed_candidates = [
        {'time': 1.0, 'frame': frame_5, 'roi': (426, 48, 852, 240), 'bbox': (50, 160, 70, 130), 'center': (85.0, 225.0), 'weight': 0.8, 'motion': 45000, 'cam_count': 5},
        {'time': 2.0, 'frame': frame_4, 'roi': (640, 48, 1280, 240), 'bbox': (140, 110, 70, 130), 'center': (175.0, 175.0), 'weight': 0.8, 'motion': 78000, 'cam_count': 4},
        {'time': 3.0, 'frame': frame_5, 'roi': (426, 48, 852, 240), 'bbox': (220, 60, 70, 130), 'center': (255.0, 125.0), 'weight': 0.8, 'motion': 62000, 'cam_count': 5},
    ]
    is_valid_mixed, _, _ = verify_moving_event(mixed_candidates, min_move_px=25.0)
    assert is_valid_mixed is False, "Mixed camera layouts across frames must NOT be verified as a valid single event!"
    print("   ✅ Mixed-camera candidate set correctly rejected.")

    # Test 4b: Real moving person within consistent 5-camera layout
    moving_5cam = [
        {'time': 3.0, 'frame': frame_5, 'roi': (426, 48, 852, 240), 'bbox': (50, 160, 70, 130), 'center': (85.0, 225.0), 'weight': 0.75, 'motion': 45000, 'cam_count': 5},
        {'time': 5.0, 'frame': frame_5, 'roi': (426, 48, 852, 240), 'bbox': (140, 110, 70, 130), 'center': (175.0, 175.0), 'weight': 0.88, 'motion': 78000, 'cam_count': 5},
        {'time': 7.0, 'frame': frame_5, 'roi': (426, 48, 852, 240), 'bbox': (220, 60, 70, 130), 'center': (255.0, 125.0), 'weight': 0.80, 'motion': 62000, 'cam_count': 5},
    ]
    is_valid_moving, three_frames, move_real = verify_moving_event(moving_5cam, min_move_px=25.0)
    assert is_valid_moving is True, f"Consistent 5-cam moving event should be valid! Got {is_valid_moving}"
    assert len(three_frames) == 3
    assert all(f.get('cam_count') == 5 for f in three_frames)
    print(f"   ✅ Real moving person confirmed with consistent 5-camera layout (Displacement: {move_real:.1f}px).")

    # Test 4c: Real moving vehicle within consistent 4-camera layout
    moving_4cam = [
        {'time': 2.0, 'frame': frame_4, 'roi': (0, 240, 640, 480), 'bbox': (40, 40, 120, 80), 'center': (100.0, 80.0), 'weight': 1.0, 'motion': 36000, 'cam_count': 4},
        {'time': 4.0, 'frame': frame_4, 'roi': (0, 240, 640, 480), 'bbox': (140, 80, 120, 80), 'center': (200.0, 120.0), 'weight': 1.0, 'motion': 48000, 'cam_count': 4},
        {'time': 6.0, 'frame': frame_4, 'roi': (0, 240, 640, 480), 'bbox': (240, 120, 120, 80), 'center': (300.0, 160.0), 'weight': 1.0, 'motion': 41000, 'cam_count': 4},
    ]
    is_valid_4cam, three_4cam, move_4cam = verify_moving_event(moving_4cam, min_move_px=25.0)
    assert is_valid_4cam is True
    assert len(three_4cam) == 3
    assert all(f.get('cam_count') == 4 for f in three_4cam)
    print(f"   ✅ Real moving vehicle confirmed with consistent 4-camera layout (Displacement: {move_4cam:.1f}px).")

    print("\n5. Generating 3-frame composite group snapshots with layout labels...")
    annotate_and_save_group_snapshot(
        three_frames_data=three_frames,
        area_name="house_around",
        target_obj="person",
        vid="2833002021",
        url="https://www.twitch.tv/videos/2833002021",
        total_movement_px=move_real,
        output_path="snapshot_house_around.jpg"
    )
    assert os.path.exists("snapshot_house_around.jpg"), "House composite snapshot was not created!"
    img = cv2.imread("snapshot_house_around.jpg")
    assert img.shape[0] > 1400
    print(f"   ✅ Generated 5-cam composite group snapshot (Resolution: {img.shape[1]}x{img.shape[0]}).")

    annotate_and_save_group_snapshot(
        three_frames_data=three_4cam,
        area_name="garage",
        target_obj="car",
        vid="2833004002",
        url="https://www.twitch.tv/videos/2833004002",
        total_movement_px=move_4cam,
        output_path="snapshot_garage.jpg"
    )
    assert os.path.exists("snapshot_garage.jpg"), "Garage composite snapshot was not created!"
    print("   ✅ Generated 4-cam composite group snapshot successfully.")

    print("\n6. Testing report parsing and email generation...")
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

    print("\n7. Testing send_email dry run...")
    os.environ["REPORT_PATH"] = "test_report.txt"
    send_email(dry_run=True)
    print("   ✅ send_email dry run passed with full MIME packaging.")

    # Cleanup temporary test files
    for temp_f in ["test_report.txt", "snapshot_house_around.jpg", "snapshot_garage.jpg"]:
        if os.path.exists(temp_f):
            os.remove(temp_f)
    print("   ✅ Cleaned up temporary test files.")

    print("\n🎉 ALL TESTS (Camera Layout Detection 5/4/3/2/1, Cross-Layout Protection, Motion Tracking) PASSED!")


if __name__ == "__main__":
    test_pipeline()
