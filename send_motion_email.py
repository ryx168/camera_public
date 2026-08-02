#!/usr/bin/env python3
"""
send_motion_email.py
Parses report.txt, detects motion/person events, embeds detection screenshots,
and delivers a responsive HTML + plain-text email with inline images and attachments.
"""

import os
import sys
import glob
import re
import datetime
from datetime import timezone
import smtplib
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

try:
    from zoneinfo import ZoneInfo
    PST_TZ = ZoneInfo("America/Los_Angeles")
except Exception:
    PST_TZ = datetime.timezone(datetime.timedelta(hours=-7), name="PDT")


def get_pst_time():
    """Get current datetime in US Pacific timezone (PST/PDT)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("America/Los_Angeles"))
    except Exception:
        try:
            return datetime.datetime.now(PST_TZ)
        except Exception:
            return datetime.datetime.now().astimezone()

# Ensure UTF-8 output for console logging across Windows/Linux
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def parse_report_file(report_path="report.txt"):
    """Parse report.txt into structured area reports."""
    if not os.path.exists(report_path):
        return [], "No report file generated."

    with open(report_path, "r", encoding="utf-8", errors="replace") as f:
        raw_text = f.read()

    sections = []
    # Split by area header e.g. === Report for house_around (person) ===
    raw_sections = re.split(r"===\s*Report for\s+([^=]+)\s*===", raw_text)

    if len(raw_sections) <= 1:
        # Single block without section headers
        has_detection = "OBJECT FOUND!" in raw_text or "PERSON FOUND!" in raw_text
        return [{
            "area_name": "General Check",
            "target_object": "all",
            "detected": has_detection,
            "raw_content": raw_text.strip(),
            "top_video": extract_first_match(r"Top video:\s*(https?://[^\s]+(?:\s+at\s+[\d\.]+s)?)", raw_text),
            "video_url": extract_first_match(r"Top video:\s*(https?://[^\s]+)", raw_text),
            "timestamp_str": extract_first_match(r"at\s+([\d\.]+s)", raw_text),
            "score_str": extract_first_match(r"Motion Score:\s*([^\n]+)", raw_text),
            "screenshots": extract_screenshots(raw_text, "General Check"),
            "candidates": extract_candidates(raw_text)
        }], raw_text

    # Parse paired header + content
    for i in range(1, len(raw_sections), 2):
        header = raw_sections[i].strip()
        content = raw_sections[i+1].strip() if i+1 < len(raw_sections) else ""
        
        # Extract area name and target object
        m = re.match(r"([^(]+)(?:\(([^)]+)\))?", header)
        area_name = m.group(1).strip() if m else header
        target_obj = m.group(2).strip() if m and m.group(2) else "motion"

        detected = "OBJECT FOUND!" in content or "PERSON FOUND!" in content
        video_match = re.search(r"Top video:\s*(https?://[^\s]+)", content)
        video_url = video_match.group(1) if video_match else ""
        t_match = re.search(r"at\s+([\d\.]+)s", content)
        timestamp_str = f"{t_match.group(1)}s" if t_match else ""
        score_str = extract_first_match(r"Motion Score:\s*([^\n]+)", content)
        screenshots = extract_screenshots(content, area_name)

        candidates = extract_candidates(content)

        sections.append({
            "area_name": area_name,
            "target_object": target_obj,
            "detected": detected,
            "raw_content": content,
            "top_video": f"{video_url} at {timestamp_str}" if video_url and timestamp_str else video_url,
            "video_url": video_url,
            "timestamp_str": timestamp_str,
            "score_str": score_str,
            "screenshots": screenshots,
            "candidates": candidates
        })

    return sections, raw_text


def extract_first_match(pattern, text):
    m = re.search(pattern, text)
    return m.group(1).strip() if m else ""


def extract_candidates(text):
    return re.findall(r"Rank\s+\d+:\s*(https?://[^\n]+)", text)


def extract_screenshots(text, area_name):
    """
    Extract the (up to 3) START/PEAK/END screenshots near the detection time
    from lines like: 'Screenshot [PEAK] at 14.1s: snapshot_house_around_peak.jpg'.
    Falls back to a legacy single 'Screenshot: path' line, and finally to any
    snapshot_<area>_*.jpg files that exist on disk, so older report formats
    still work.
    """
    shots = []
    for m in re.finditer(r"Screenshot\s*\[(\w+)\]\s*at\s*([\d\.]+)s:\s*([^\n]+)", text):
        phase, t_str, path = m.group(1), m.group(2), m.group(3).strip()
        if os.path.exists(path):
            shots.append({"phase": phase, "time": t_str, "path": path})

    if not shots:
        legacy = extract_first_match(r"Screenshot:\s*([^\n]+)", text)
        if legacy and os.path.exists(legacy):
            shots.append({"phase": "DETECTION", "time": "", "path": legacy})

    if not shots:
        # Fallback: glob for files saved by the current naming scheme
        safe_area = re.sub(r"[^a-zA-Z0-9_]+", "_", area_name.strip().lower())
        phase_order = {"start": 0, "peak": 1, "end": 2}
        found = sorted(
            glob.glob(f"snapshot_{safe_area}_*.jpg"),
            key=lambda p: phase_order.get(Path(p).stem.split("_")[-1], 99)
        )
        for path in found:
            phase = Path(path).stem.split("_")[-1].upper()
            shots.append({"phase": phase, "time": "", "path": path})

    return shots[:3]


def build_email_content(sections, raw_text):
    """Build dynamic subject, plain-text body, and HTML body."""
    now_pst = get_pst_time()
    tz_abbr = now_pst.strftime("%Z") or "PST"
    now_pst_str = now_pst.strftime(f"%Y-%m-%d %I:%M %p {tz_abbr}")
    now_utc = datetime.datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    
    detected_areas = [s["area_name"] for s in sections if s["detected"]]
    has_any_detection = len(detected_areas) > 0

    if has_any_detection:
        subject = f"🚨 [MOTION DETECTED] Twitch Camera Alert ({', '.join(detected_areas)}) - {now_pst_str}"
    else:
        subject = f"✅ [All Clear] Twitch Motion Check Report - {now_pst_str}"

    # Plain text version
    plain_body = f"""====================================================
TWITCH 3-HOUR MOTION CHECK REPORT
====================================================
Check Time: {now_pst_str} ({now_utc})
Overall Status: {'🚨 MOTION / OBJECT DETECTED' if has_any_detection else '✅ ALL CLEAR - NO MOTION DETECTED'}
Detected Areas: {', '.join(detected_areas) if detected_areas else 'None'}
====================================================

{raw_text}

====================================================
Automated notification from GitHub Actions 3-Hour Surveillance Workflow.
"""

    # HTML version
    header_gradient = "linear-gradient(135deg, #dc2626 0%, #991b1b 100%)" if has_any_detection else "linear-gradient(135deg, #059669 0%, #047857 100%)"
    status_icon = "🚨" if has_any_detection else "✅"
    status_title = "Motion Detected Alert" if has_any_detection else "All Clear - No Motion Detected"
    status_subtitle = f"Activity detected in <b>{', '.join(detected_areas)}</b> in the last 3 hours" if has_any_detection else "No significant motion or target objects detected in the last 3 hours"

    # Build section cards HTML
    section_cards_html = ""
    for s in sections:
        area_title = s["area_name"].replace("_", " ").title()
        target_title = s["target_object"].replace("_", " ").title()
        
        if s["detected"]:
            card_border = "#ef4444"
            badge_bg = "#fee2e2"
            badge_color = "#991b1b"
            badge_text = "🚨 OBJECT DETECTED"
        else:
            card_border = "#e2e8f0"
            badge_bg = "#ecfdf5"
            badge_color = "#065f46"
            badge_text = "✅ ALL CLEAR"

        shot_html = ""
        if s["detected"] and s.get("screenshots"):
            shot_cells = ""
            for shot in s["screenshots"]:
                cid_name = Path(shot["path"]).name
                phase_label = shot["phase"].title()
                time_label = f" at {shot['time']}s" if shot.get("time") else ""
                shot_cells += f"""
                <td style="padding: 6px; text-align: center; vertical-align: top; width: 33%;">
                    <div style="font-size: 11px; color: #94a3b8; margin-bottom: 6px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">
                        {phase_label}{time_label}
                    </div>
                    <a href="{s['video_url']}" target="_blank" style="display: block; text-decoration: none;">
                        <img src="cid:{cid_name}" alt="{area_title} {phase_label} Screenshot" style="width: 100%; height: auto; border-radius: 6px; border: 1px solid #334155; display: block;" />
                    </a>
                </td>
                """
            shot_html = f"""
            <div style="margin-top: 16px; background: #0f172a; padding: 12px; border-radius: 8px;">
                <div style="font-size: 12px; color: #94a3b8; margin-bottom: 8px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; text-align: center;">
                    📸 Screenshots Near Detection Time ({s['timestamp_str']})
                </div>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>{shot_cells}</tr>
                </table>
                <div style="margin-top: 8px; font-size: 11px; color: #64748b; text-align: center;">
                    Click any image to open the Twitch stream
                </div>
            </div>
            """

        details_html = ""
        if s["detected"]:
            details_html = f"""
            <table style="width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 14px;">
                <tr>
                    <td style="padding: 6px 0; color: #64748b; width: 130px; font-weight: 500;">Top Video:</td>
                    <td style="padding: 6px 0; font-weight: 600;">
                        <a href="{s['video_url']}" target="_blank" style="color: #7c3aed; text-decoration: none;">
                            {s['video_url']}
                        </a>
                    </td>
                </tr>
                <tr>
                    <td style="padding: 6px 0; color: #64748b; font-weight: 500;">Timestamp:</td>
                    <td style="padding: 6px 0; font-weight: bold; color: #dc2626;">{s['timestamp_str']}</td>
                </tr>
                {f'<tr><td style="padding: 6px 0; color: #64748b; font-weight: 500;">Metrics:</td><td style="padding: 6px 0; color: #334155;">{s["score_str"]}</td></tr>' if s.get("score_str") else ''}
            </table>
            <div style="margin-top: 14px;">
                <a href="{s['video_url']}" target="_blank" style="display: inline-block; background-color: #9146FF; color: #ffffff; padding: 8px 16px; border-radius: 6px; text-decoration: none; font-size: 13px; font-weight: bold;">
                    ▶ Watch on Twitch at {s['timestamp_str']}
                </a>
            </div>
            """
            if s.get("candidates"):
                cand_list = "".join([f"<li style='margin-bottom: 4px;'><a href='{c.split()[0]}' target='_blank' style='color:#6366f1; text-decoration:none;'>{c}</a></li>" for c in s["candidates"][:4]])
                details_html += f"""
                <div style="margin-top: 14px; padding-top: 10px; border-top: 1px dashed #cbd5e1; font-size: 12px; color: #64748b;">
                    <b>Other candidates:</b>
                    <ul style="margin: 6px 0 0 0; padding-left: 20px; color: #475569;">{cand_list}</ul>
                </div>
                """
        else:
            details_html = f"""
            <p style="margin: 8px 0 0 0; font-size: 14px; color: #475569;">
                No motion or {target_title.lower()} detected in this zone during the 3-hour inspection window.
            </p>
            """

        section_cards_html += f"""
        <div style="background-color: #ffffff; border: 2px solid {card_border}; border-radius: 10px; padding: 18px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.04);">
            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #f1f5f9; padding-bottom: 10px;">
                <div>
                    <h3 style="margin: 0; font-size: 17px; color: #0f172a;">{area_title}</h3>
                    <span style="font-size: 12px; color: #64748b;">Target: <b>{target_title}</b></span>
                </div>
                <span style="background-color: {badge_bg}; color: {badge_color}; font-size: 12px; font-weight: bold; padding: 4px 10px; border-radius: 9999px; text-transform: uppercase;">
                    {badge_text}
                </span>
            </div>
            {details_html}
            {shot_html}
        </div>
        """

    html_body = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{subject}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b; line-height: 1.5;">
    <div style="max-width: 680px; margin: 20px auto; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.08); border: 1px solid #e2e8f0;">
        
        <!-- Header Banner -->
        <div style="background: {header_gradient}; color: #ffffff; padding: 24px 20px; text-align: center;">
            <div style="font-size: 32px; margin-bottom: 4px;">{status_icon}</div>
            <h1 style="margin: 0; font-size: 22px; font-weight: 700; letter-spacing: -0.5px;">{status_title}</h1>
            <p style="margin: 6px 0 0 0; font-size: 14px; opacity: 0.9;">{status_subtitle}</p>
        </div>

        <!-- Meta Summary Bar -->
        <div style="background-color: #f1f5f9; padding: 12px 20px; font-size: 13px; color: #475569; border-bottom: 1px solid #e2e8f0;">
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td><b>Time (PST/PDT):</b> {now_pst_str}</td>
                    <td style="text-align: right;"><b>UTC:</b> {now_utc}</td>
                </tr>
            </table>
        </div>

        <!-- Content Area -->
        <div style="padding: 24px 20px;">
            {section_cards_html}

            <!-- Raw Report Collapsible/Box -->
            <div style="margin-top: 20px; background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px;">
                <div style="font-size: 12px; font-weight: 700; color: #475569; text-transform: uppercase; margin-bottom: 8px;">
                    📄 Raw Inspection Report
                </div>
                <pre style="margin: 0; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; color: #334155; white-space: pre-wrap; word-break: break-word;">{raw_text.strip()}</pre>
            </div>
        </div>

        <!-- Footer -->
        <div style="background-color: #f8fafc; border-top: 1px solid #e2e8f0; padding: 16px 20px; text-align: center; font-size: 12px; color: #94a3b8;">
            <p style="margin: 0;">Automated 3-Hour Surveillance Check &bull; Twitch Stream AI Monitor</p>
        </div>
    </div>
</body>
</html>
"""

    return subject, plain_body, html_body


def send_email(dry_run=False):
    """Parse report, build email with attachments, and dispatch via SMTP."""
    report_path = os.environ.get("REPORT_PATH", "report.txt")
    sections, raw_text = parse_report_file(report_path)
    subject, plain_body, html_body = build_email_content(sections, raw_text)

    # Collect all screenshot images to attach (up to 3 per section)
    images_to_attach = []
    # 1. From parsed sections
    for s in sections:
        for shot in s.get("screenshots", []):
            path = shot.get("path")
            if path and os.path.exists(path) and path not in images_to_attach:
                images_to_attach.append(path)

    # 2. Any additional snapshot_*.jpg files in current directory
    for f in glob.glob("snapshot_*.jpg"):
        if f not in images_to_attach:
            images_to_attach.append(f)

    print(f"Parsed {len(sections)} sections. Found {len(images_to_attach)} snapshot image(s): {images_to_attach}")

    # Build MIME Message
    # Use MIMEMultipart("mixed") root with nested MIMEMultipart("alternative")
    msg_root = MIMEMultipart("mixed")
    msg_root["Subject"] = subject
    
    from_addr = os.environ.get("SMTP_FROM") or "harry@superesolutions.com"
    to_addr = os.environ.get("SMTP_TO") or "harry@superesolutions.com"
    msg_root["From"] = from_addr
    msg_root["To"] = to_addr

    # Add alternative part (plain text + html)
    msg_alt = MIMEMultipart("alternative")
    msg_alt.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg_alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg_root.attach(msg_alt)

    # Attach images with Content-ID for inline rendering and Content-Disposition for download
    for img_path in images_to_attach:
        try:
            with open(img_path, "rb") as f:
                img_data = f.read()
            filename = os.path.basename(img_path)
            img_part = MIMEImage(img_data)
            img_part.add_header("Content-ID", f"<{filename}>")
            img_part.add_header("Content-Disposition", "inline", filename=filename)
            msg_root.attach(img_part)
            print(f"Attached image: {filename} (Content-ID: <{filename}>, {len(img_data)} bytes)")
        except Exception as e:
            print(f"Warning: Failed to attach image {img_path}: {e}")

    if dry_run:
        print("\n=== DRY RUN MODE (Email not sent) ===")
        print(f"Subject: {subject}")
        print(f"From: {from_addr}")
        print(f"To: {to_addr}")
        print(f"Attachments: {len(images_to_attach)}")
        print(f"HTML Body Length: {len(html_body)} chars")
        return True

    # SMTP Configuration
    smtp_host = os.environ.get("SMTP_SERVER") or os.environ.get("SMTP_HOST") or "smtp.postmarkapp.com"
    smtp_port = int(os.environ.get("SMTP_PORT") or 587)
    smtp_user = os.environ.get("SMTP_USERNAME") or os.environ.get("SMTP_USER") or "8f23463b-5db0-4bfb-9adc-fa13016656d2"
    smtp_pass = os.environ.get("SMTP_PASSWORD") or os.environ.get("SMTP_PASS") or "8f23463b-5db0-4bfb-9adc-fa13016656d2"

    print(f"Connecting to SMTP server {smtp_host}:{smtp_port}...")
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg_root)
        print(f"✅ Report email delivered successfully to {to_addr}!")
        return True
    except Exception as e:
        print(f"❌ Error sending report email: {e}")
        # Re-raise to fail workflow if needed
        raise e


if __name__ == "__main__":
    is_dry_run = "--dry-run" in sys.argv
    send_email(dry_run=is_dry_run)