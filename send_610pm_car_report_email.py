#!/usr/bin/env python3
import os
import sys
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

def send_car_report():
    subject = "🚨 Security Alert: Vehicle Activity Detected at 6:10 PM PDT (Stream AI Report)"
    
    from_addr = os.environ.get("SMTP_FROM") or "harry@superesolutions.com"
    to_addr = os.environ.get("SMTP_TO") or "harry@superesolutions.com"
    
    # SMTP credentials
    smtp_host = os.environ.get("SMTP_SERVER") or os.environ.get("SMTP_HOST") or "smtp.postmarkapp.com"
    smtp_port = int(os.environ.get("SMTP_PORT") or 587)
    smtp_user = os.environ.get("SMTP_USERNAME") or os.environ.get("SMTP_USER") or "8f23463b-5db0-4bfb-9adc-fa13016656d2"
    smtp_pass = os.environ.get("SMTP_PASSWORD") or os.environ.get("SMTP_PASS") or "8f23463b-5db0-4bfb-9adc-fa13016656d2"
    
    # Images to embed
    images = [
        ("truck_street", "c:/camera/vehicle_highlights/truck_610pm_24.0s_street.jpg", "Vehicle Close-up (White Pickup Truck & Trailer)"),
        ("truck_front", "c:/camera/vehicle_highlights/truck_610pm_24.0s_front.jpg", "Front Porch & Street View at 6:10:31 PM PDT"),
        ("truck_full", "c:/camera/vehicle_highlights/truck_610pm_24.0s_full.jpg", "5-Camera Surveillance Grid at 6:10:31 PM PDT")
    ]
    
    plain_text = f"""
=====================================================
🚨 VEHICLE / CAR ACTIVITY REPORT - 6:10 PM PDT
=====================================================

Inspection Time: Tuesday, August 4, 2026 around 6:10 PM PDT
Stream Channel: elarathornfield168

SUMMARY OF FINDINGS:
--------------------
1. EXACT 6:10 PM VEHICLE DETECTION:
   - Time: 2026-08-04 06:10:31 PM PDT (VOD v2837528327 at +24.0s)
   - Vehicle: White pickup truck hauling a white trailer / camper driving by the front street / driveway entrance.
   - Twitch VOD URL: https://www.twitch.tv/videos/2837528327
   - Motion Area: 9,157 px detected across Front Camera street boundary.

2. DRIVEWAY & SURROUNDING ACTIVITY:
   - White vehicle parked on the right driveway perimeter behind porch post.
   - Subsequent motion detected at 6:18 PM (v2837535220) and 6:24 PM (v2837540541).

Please see the attached high-resolution surveillance images for visual confirmation.
"""

    html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0f172a; margin: 0; padding: 20px; color: #334155; }}
    .container {{ max-width: 680px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.3); border: 1px solid #e2e8f0; }}
    .header {{ background: linear-gradient(135deg, #b91c1c 0%, #dc2626 50%, #991b1b 100%); color: #ffffff; padding: 26px 20px; text-align: center; }}
    .badge {{ background-color: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; font-size: 13px; font-weight: 700; padding: 4px 12px; border-radius: 20px; text-transform: uppercase; }}
    .meta-bar {{ background-color: #f8fafc; padding: 12px 20px; font-size: 13px; border-bottom: 1px solid #e2e8f0; color: #475569; }}
    .card {{ background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 18px; margin: 20px; box-shadow: 0 2px 6px rgba(0,0,0,0.04); }}
    .card-title {{ font-size: 17px; font-weight: 700; color: #0f172a; margin-top: 0; margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between; }}
    .info-table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 14px; }}
    .info-table td {{ padding: 8px 10px; border-bottom: 1px solid #f1f5f9; }}
    .info-table td.label {{ font-weight: 600; color: #64748b; width: 35%; }}
    .btn {{ display: inline-block; background: linear-gradient(135deg, #2563eb, #1d4ed8); color: #ffffff !important; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; margin-top: 12px; }}
    .img-box {{ margin-top: 15px; border-radius: 6px; overflow: hidden; border: 1px solid #cbd5e1; background: #000; text-align: center; }}
    .img-box img {{ max-width: 100%; height: auto; display: block; }}
    .img-caption {{ background: #1e293b; color: #94a3b8; font-size: 12px; padding: 6px 10px; text-align: left; }}
    .footer {{ background-color: #f8fafc; border-top: 1px solid #e2e8f0; padding: 16px 20px; text-align: center; font-size: 12px; color: #94a3b8; }}
</style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <div style="font-size: 36px; margin-bottom: 6px;">🚗 🚨</div>
            <h1 style="margin: 0; font-size: 24px; font-weight: 800; letter-spacing: -0.5px;">Vehicle Activity Confirmed</h1>
            <p style="margin: 6px 0 0 0; font-size: 14px; opacity: 0.95;">Surveillance Scan around 6:10 PM PDT</p>
        </div>

        <!-- Meta Bar -->
        <div class="meta-bar">
            <table style="width: 100%;">
                <tr>
                    <td><b>Time (Pacific):</b> <span style="color: #0f172a; font-weight: 700;">Tuesday, Aug 4, 2026 ~ 06:10:31 PM PDT</span></td>
                    <td style="text-align: right;"><span class="badge">Vehicle Detected</span></td>
                </tr>
            </table>
        </div>

        <!-- Main Card -->
        <div class="card" style="border-left: 4px solid #dc2626;">
            <div class="card-title">
                <span>🎯 Primary Vehicle Sighting (6:10 PM)</span>
                <span style="font-size: 12px; color: #dc2626; font-weight: 700;">CONFIRMED</span>
            </div>
            <table class="info-table">
                <tr>
                    <td class="label">Exact Timestamp:</td>
                    <td><b>2026-08-04 06:10:31 PM PDT</b> (+24.0s into VOD)</td>
                </tr>
                <tr>
                    <td class="label">Target Vehicle:</td>
                    <td><b style="color: #b91c1c;">White Pickup Truck pulling a White Trailer / Camper</b></td>
                </tr>
                <tr>
                    <td class="label">Location / Zone:</td>
                    <td>Front Street / Driveway Entrance (Front Camera)</td>
                </tr>
                <tr>
                    <td class="label">Motion Intensity:</td>
                    <td>Area <b>9,157 px</b> (High Confidence Anomaly)</td>
                </tr>
                <tr>
                    <td class="label">VOD ID:</td>
                    <td><code>v2837528327</code></td>
                </tr>
            </table>
            
            <div style="text-align: center; margin-top: 15px;">
                <a href="https://www.twitch.tv/videos/2837528327" class="btn">📺 Watch VOD on Twitch (v2837528327)</a>
            </div>

            <!-- Close up image -->
            <div class="img-box">
                <img src="cid:truck_street" alt="Vehicle Close-up">
                <div class="img-caption">🔍 <b>Close-Up Crop:</b> White Pickup Truck + Trailer passing the driveway at 6:10:31 PM PDT</div>
            </div>

            <!-- Front camera image -->
            <div class="img-box">
                <img src="cid:truck_front" alt="Front Porch View">
                <div class="img-caption">📸 <b>Front Camera View:</b> Front porch stairs, street view, and parked vehicle at 6:10:31 PM PDT</div>
            </div>
        </div>

        <!-- 5-Camera Full Grid Card -->
        <div class="card">
            <div class="card-title">
                <span>📹 Complete 5-Camera Surveillance Snapshot</span>
            </div>
            <p style="font-size: 13px; color: #475569; margin: 0 0 10px 0;">Synchronized snapshot across all 5 active camera angles (Office, Front, Kitchen, Balcony, Backyard) at the moment of vehicle detection.</p>
            <div class="img-box">
                <img src="cid:truck_full" alt="Full Surveillance Composite">
                <div class="img-caption">🖥️ <b>5-Camera Composite:</b> Office (Top-L), Front (Top-M), Kitchen (Top-R), Balcony (Bot-L), Backyard (Bot-R)</div>
            </div>
        </div>

        <!-- Additional Chronological Observations -->
        <div class="card" style="background-color: #f8fafc;">
            <div class="card-title" style="font-size: 15px; margin-bottom: 8px;">
                <span>📋 Additional Timeline Events</span>
            </div>
            <ul style="margin: 0; padding-left: 20px; font-size: 13px; color: #475569; line-height: 1.6;">
                <li><b>06:00 PM - 06:09 PM:</b> Normal street background, white vehicle present on right driveway approach.</li>
                <li><b>06:10:31 PM PDT (VOD v2837528327):</b> White truck with trailer passes directly across the front street and driveway view.</li>
                <li><b>06:18:08 PM PDT (VOD v2837535220):</b> Activity and light reflection across Front & Kitchen camera sectors.</li>
                <li><b>06:24:26 PM PDT (VOD v2837540541):</b> Major driveway motion detected in Kitchen camera view (Area 14,935 px).</li>
            </ul>
        </div>

        <!-- Footer -->
        <div class="footer">
            <p style="margin: 0;">Automated AI Camera Surveillance &bull; Security Detection System &bull; Postmark Delivery</p>
        </div>
    </div>
</body>
</html>
"""

    msg_root = MIMEMultipart("mixed")
    msg_root["Subject"] = subject
    msg_root["From"] = from_addr
    msg_root["To"] = to_addr

    msg_alt = MIMEMultipart("alternative")
    msg_alt.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg_alt.attach(MIMEText(html_content, "html", "utf-8"))
    msg_root.attach(msg_alt)

    # Attach images with CID
    for cid, file_path, desc in images:
        if os.path.exists(file_path):
            with open(file_path, "rb") as f:
                img_data = f.read()
            img_part = MIMEImage(img_data)
            img_part.add_header("Content-ID", f"<{cid}>")
            img_part.add_header("Content-Disposition", "inline", filename=os.path.basename(file_path))
            msg_root.attach(img_part)
            print(f"Attached {file_path} as CID <{cid}> ({len(img_data)} bytes)")

    print(f"Connecting to Postmark SMTP {smtp_host}:{smtp_port}...")
    with smtplib.SMTP(smtp_host, smtp_port, timeout=25) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg_root)
    print(f"[SUCCESS] Vehicle report email sent successfully to {to_addr}!")

if __name__ == "__main__":
    send_car_report()
