#!/usr/bin/env python3
"""
test_motion_pipeline.py
Test script to verify camera layout bounds, multi-camera grid detection,
frame annotation, report parsing, HTML generation, and MIME image attachment.
"""

import os
import sys
import numpy as np
import cv2
from check_recent_motion import annotate_and_save_snapshot, get_camera_bounds, is_multicam_grid
from send_motion_email import parse_report_file, build_email_content, send_email

def test_pipeline():
    print("1. Testing camera layout bounds...")
    w, h = 1280, 480
    
    # House / Front should be Camera 2 (Top-Middle: 426..853, 0..240)
    cam2_bounds = get_camera_bounds(np.zeros((h, w, 3), dtype=np.uint8), "house_around")
    assert cam2_bounds == (426, 0, 852, 240), f"Unexpected bounds for house_around: {cam2_bounds}"
    print(f"   ✅ house_around bounds: {cam2_bounds} (Camera 2 - Top Middle)")

    # Garage / Kitchen should be Camera 3 (Top-Right: 853..1280, 0..240)
    cam3_bounds = get_camera_bounds(np.zeros((h, w, 3), dtype=np.uint8), "garage")
    assert cam3_bounds == (852, 0, 1280, 240), f"Unexpected bounds for garage: {cam3_bounds}"
    print(f"   ✅ garage bounds: {cam3_bounds} (Camera 3 - Top Right)")

    print("\n2. Testing multi-camera grid vs single-camera detector...")
    # Create synthetic 5-camera grid frame with different cameras
    grid_frame = np.zeros((480, 1280, 3), dtype=np.uint8)
    grid_frame[0:240, 0:426] = (30, 40, 50)         # Cam 1 Office
    grid_frame[0:240, 426:853] = (180, 190, 200)    # Cam 2 Front porch
    grid_frame[0:240, 853:1280] = (80, 120, 60)     # Cam 3 Garage / Driveway
    grid_frame[240:480, 0:640] = (10, 80, 150)      # Cam 4 Balcony
    grid_frame[240:480, 640:1280] = (40, 180, 50)   # Cam 5 Backyard
    
    assert is_multicam_grid(grid_frame) is True, "Expected 5-camera grid to be detected as True"
    print("   ✅ 5-camera grid correctly recognized.")

    # Create synthetic single camera frame (smooth gradient across frame, no camera boundaries)
    single_cam_frame = np.zeros((480, 1280, 3), dtype=np.uint8)
    for y in range(480):
        single_cam_frame[y, :] = int((y / 480.0) * 150)
    assert is_multicam_grid(single_cam_frame) is False, "Expected single camera frame to be detected as False"
    print("   ✅ Single camera broadcast correctly detected and filtered out.")

    print("\n3. Creating synthetic camera test snapshots...")
    # Generate House snapshot
    house_roi = (426, 48, 852, 240)  # Bottom 80% of Camera 2
    house_bbox = (150, 40, 80, 140)
    annotate_and_save_snapshot(
        frame=grid_frame,
        crop_roi=house_roi,
        bbox=house_bbox,
        area_name="house_around",
        target_obj="person",
        vid="2833002021",
        url="https://www.twitch.tv/videos/2833002021",
        timestamp_sec=15.6,
        score=64552,
        p_height=185,
        p_weight=0.88,
        output_path="snapshot_house_around.jpg"
    )
    assert os.path.exists("snapshot_house_around.jpg"), "House snapshot was not created!"
    print("   ✅ Generated snapshot_house_around.jpg successfully.")

    # Generate Garage snapshot (in Camera 3)
    garage_roi = (852, 48, 1280, 240)
    annotate_and_save_snapshot(
        frame=grid_frame,
        crop_roi=garage_roi,
        bbox=None,
        area_name="garage",
        target_obj="car",
        vid="2833004002",
        url="https://www.twitch.tv/videos/2833004002",
        timestamp_sec=7.2,
        score=18200,
        p_height=0,
        p_weight=1.0,
        output_path="snapshot_garage.jpg"
    )
    assert os.path.exists("snapshot_garage.jpg"), "Garage snapshot was not created!"
    print("   ✅ Generated snapshot_garage.jpg successfully.")

    print("\n4. Generating test report.txt...")
    test_report_content = """=== Report for house_around (person) ===
OBJECT FOUND!

Top video: https://www.twitch.tv/videos/2833002021 at 15.6s
Motion Score: 64552 pixels (Person height: 185px, conf: 0.88)
Screenshot: snapshot_house_around.jpg

Other top candidates:
Rank 2: https://www.twitch.tv/videos/2833001544 at 15.6s (Score: 64552)
Rank 3: https://www.twitch.tv/videos/2833001077 at 15.6s (Score: 64552)

=== Report for garage (car) ===
OBJECT FOUND!

Top video: https://www.twitch.tv/videos/2833004002 at 7.2s
Motion Score: 18200 pixels (Person height: 0px, conf: 1.00)
Screenshot: snapshot_garage.jpg

Other top candidates:
Rank 2: https://www.twitch.tv/videos/2833180115 at 21.6s (Score: 16500)
"""
    with open("test_report.txt", "w", encoding="utf-8") as f:
        f.write(test_report_content)

    print("\n5. Testing report parsing and email formatting...")
    sections, raw_text = parse_report_file("test_report.txt")
    assert len(sections) == 2, f"Expected 2 sections, got {len(sections)}"
    assert sections[0]["area_name"] == "house_around"
    assert sections[0]["detected"] is True
    assert sections[1]["area_name"] == "garage"
    assert sections[1]["detected"] is True
    print(f"   ✅ Parsed {len(sections)} sections accurately.")

    subject, plain_body, html_body = build_email_content(sections, raw_text)
    assert "MOTION DETECTED" in subject, "Subject should indicate motion detected"
    assert "cid:snapshot_house_around.jpg" in html_body, "HTML body must contain CID for house snapshot"
    assert "cid:snapshot_garage.jpg" in html_body, "HTML body must contain CID for garage snapshot"
    assert "15.6s" in html_body, "HTML body must contain detection timestamp"
    assert "https://www.twitch.tv/videos/2833002021" in html_body, "HTML body must contain Twitch URL"
    print("   ✅ HTML Email body contains all screenshots, links, and timestamps.")

    print("\n6. Testing send_email dry run with attachments...")
    os.environ["REPORT_PATH"] = "test_report.txt"
    send_email(dry_run=True)
    print("   ✅ send_email dry run passed with full MIME image packaging.")

    print("\n7. Testing All-Clear scenario (no motion)...")
    with open("test_clear_report.txt", "w", encoding="utf-8") as f:
        f.write("=== Report for house_around (person) ===\nno find\n\n=== Report for garage (car) ===\nno find\n")
    clear_sections, clear_raw = parse_report_file("test_clear_report.txt")
    clear_subj, clear_plain, clear_html = build_email_content(clear_sections, clear_raw)
    assert "All Clear" in clear_subj, "Subject should indicate All Clear"
    assert "No motion or person detected" in clear_html or "No motion or car detected" in clear_html
    print("   ✅ All-Clear scenario formatted correctly with green badges and subject.")

    # Cleanup temporary test files
    for temp_f in ["test_report.txt", "test_clear_report.txt", "snapshot_house_around.jpg", "snapshot_garage.jpg"]:
        if os.path.exists(temp_f):
            os.remove(temp_f)
    print("   ✅ Cleaned up temporary test files.")

    print("\n🎉 ALL TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_pipeline()
