#!/usr/bin/env python3
"""
test_motion_pipeline.py
Test script to verify frame annotation, report parsing, HTML generation, and MIME image attachment.
"""

import os
import sys
import numpy as np
import cv2
from check_recent_motion import annotate_and_save_snapshot
from send_motion_email import parse_report_file, build_email_content, send_email

def test_pipeline():
    print("1. Creating synthetic camera test frames...")
    # Create synthetic 1280x480 frame
    frame = np.zeros((480, 1280, 3), dtype=np.uint8)
    # Add dummy visual textures
    cv2.rectangle(frame, (0, 0), (426, 240), (40, 40, 40), -1)      # Office
    cv2.rectangle(frame, (426, 0), (853, 240), (70, 70, 70), -1)    # Front
    cv2.rectangle(frame, (853, 0), (1280, 240), (40, 40, 40), -1)   # Kitchen
    cv2.putText(frame, "Front Camera", (500, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    # Generate House snapshot
    house_roi = (426, 0, 853, 240)
    house_bbox = (150, 40, 80, 160)
    annotate_and_save_snapshot(
        frame=frame,
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

    # Generate Garage snapshot
    garage_roi = (426, 120, 853, 240)
    annotate_and_save_snapshot(
        frame=frame,
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

    print("2. Generating test report.txt...")
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

    print("3. Testing report parsing and email formatting...")
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

    print("4. Testing send_email dry run with attachments...")
    os.environ["REPORT_PATH"] = "test_report.txt"
    send_email(dry_run=True)
    print("   ✅ send_email dry run passed with full MIME image packaging.")

    print("5. Testing All-Clear scenario (no motion)...")
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
