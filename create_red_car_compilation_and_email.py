import cv2
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

os.makedirs("kitchen_gallery_608_630", exist_ok=True)

# Key moments to assemble:
key_shots = [
    ("6:10 PM (Approach / Perimeter)", "kitchen_timeline_608_630/v2837528327_zoom_10m00s.jpg", "shot_610"),
    ("6:15 PM (Pre-Entry)", "kitchen_timeline_608_630/v2837532825_zoom_15m00s.jpg", "shot_615"),
    ("6:20 PM (Pre-Entry)", "kitchen_timeline_608_630/v2837536823_zoom_20m00s.jpg", "shot_620"),
    ("6:25 PM (Positioning)", "kitchen_timeline_608_630/v2837541368_zoom_25m00s.jpg", "shot_625"),
    ("6:27:18 PM (DRIVING IN)", "red_car_exact_arrival/v2837542994_627_PM_t18s.jpg", "shot_627_18"),
    ("6:27:22 PM (PULLING FORWARD)", "red_car_exact_arrival/v2837542994_627_PM_t20s.jpg", "shot_627_20"),
    ("6:28:15 PM (PARKED AT GARAGE)", "red_car_exact_arrival/v2837543737_628_PM_t15s.jpg", "shot_628"),
    ("6:30:00 PM (FULLY PARKED)", "kitchen_timeline_608_630/v2837545204_zoom_30m00s.jpg", "shot_630"),
]

# Create a 2x4 composite image for quick viewing
panel_imgs = []
for label, path, _ in key_shots:
    if os.path.exists(path):
        img = cv2.imread(path)
        img_res = cv2.resize(img, (360, 240))
        panel_imgs.append(img_res)
    else:
        print(f"Missing {path}")

# Row 1 (6:10 to 6:25)
row1 = cv2.hconcat(panel_imgs[0:4])
# Row 2 (6:27 to 6:30)
row2 = cv2.hconcat(panel_imgs[4:8])
grid = cv2.vconcat([row1, row2])
cv2.imwrite("kitchen_gallery_608_630/red_car_arrival_grid.jpg", grid)
print("Saved 8-panel composite grid!")

# Send Email Report via Postmark
def send_email():
    from_addr = "harry@superesolutions.com"
    to_addr = "harry@superesolutions.com"
    
    smtp_host = "smtp.postmarkapp.com"
    smtp_port = 587
    smtp_user = "8f23463b-5db0-4bfb-9adc-fa13016656d2"
    smtp_pass = "8f23463b-5db0-4bfb-9adc-fa13016656d2"
    
    subject = "🚨 Kitchen Camera (Cam 3) Timeline: Red Car Entering Garage (6:10 PM - 6:30 PM PDT)"
    
    html_body = f"""<!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b; background-color: #f8fafc; margin: 0; padding: 20px; }}
            .card {{ background: #ffffff; border-radius: 12px; max-width: 800px; margin: 0 auto; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.08); border: 1px solid #e2e8f0; }}
            .header {{ background: linear-gradient(135deg, #b91c1c, #991b1b); color: #ffffff; padding: 24px; text-align: center; }}
            .header h1 {{ margin: 0 0 6px 0; font-size: 22px; font-weight: 700; }}
            .header p {{ margin: 0; font-size: 13px; opacity: 0.9; }}
            .content {{ padding: 24px; }}
            .highlight-box {{ background: #fef2f2; border-left: 4px solid #ef4444; padding: 14px 16px; border-radius: 6px; margin: 16px 0; }}
            .highlight-title {{ font-weight: 700; color: #991b1b; font-size: 14px; margin-bottom: 4px; }}
            .table-box {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
            .table-box th, .table-box td {{ padding: 10px 12px; border: 1px solid #e2e8f0; font-size: 13px; text-align: left; }}
            .table-box th {{ background-color: #f1f5f9; color: #475569; font-weight: 600; }}
            .grid-container {{ margin: 20px 0; text-align: center; background: #0f172a; border-radius: 8px; padding: 12px; }}
            .grid-container img {{ max-width: 100%; height: auto; border-radius: 6px; }}
            .img-caption {{ color: #94a3b8; font-size: 12px; margin-top: 8px; font-weight: 500; }}
            .gallery {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0; justify-content: space-between; }}
            .gallery-item {{ flex: 1 1 calc(50% - 12px); background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; text-align: center; }}
            .gallery-item img {{ width: 100%; height: auto; display: block; }}
            .gallery-label {{ padding: 8px; font-size: 12px; font-weight: 600; color: #334155; }}
            .footer {{ background-color: #f1f5f9; padding: 14px; text-align: center; font-size: 12px; color: #64748b; border-top: 1px solid #e2e8f0; }}
        </style>
    </head>
    <body>
        <div class="card">
            <div class="header">
                <h1>Kitchen Camera (Cam 3) Surveillance Report</h1>
                <p>Timeline & Exact Entry Sequence &bull; 6:10 PM – 6:30 PM PDT</p>
            </div>
            <div class="content">
                <p>Hello Harry,</p>
                
                <div class="highlight-box">
                    <div class="highlight-title">🎯 Key Finding: Red Car Garage Entry Confirmed</div>
                    <div>
                        Inspection of the <strong>3rd Camera (Kitchen)</strong> between <strong>6:10 PM and 6:30 PM PDT</strong> captures the red car approaching and then <strong>pulling directly into the garage entrance at 6:27:18 PM – 6:27:26 PM PDT</strong>.
                    </div>
                </div>

                <h3 style="color: #0f172a; margin-top: 20px;">⏱️ Timeline of Events (Camera 3 - Kitchen)</h3>
                <table class="table-box">
                    <tr>
                        <th>Time (PDT)</th>
                        <th>VOD</th>
                        <th>Event Description</th>
                    </tr>
                    <tr>
                        <td><strong>6:10 PM</strong></td>
                        <td><code>v2837528327</code></td>
                        <td>Red car hood/corner visible near the garage boundary.</td>
                    </tr>
                    <tr>
                        <td><strong>6:15 PM – 6:25 PM</strong></td>
                        <td><code>v2837532825</code> ...</td>
                        <td>Vehicle stationary at perimeter entrance.</td>
                    </tr>
                    <tr>
                        <td><strong>6:27:18 PM – 6:27:26 PM</strong></td>
                        <td><code>v2837542994</code></td>
                        <td><strong>🚗 Active Entry:</strong> Red car accelerates forward directly into the garage/driveway entry under Camera 3.</td>
                    </tr>
                    <tr>
                        <td><strong>6:28 PM – 6:30 PM</strong></td>
                        <td><code>v2837543737</code> – <code>v2837545204</code></td>
                        <td><strong>🅿️ Parked:</strong> Red car fully parked in front of the garage entrance.</td>
                    </tr>
                </table>

                <h3 style="color: #0f172a; margin-top: 24px;">🖼️ 8-Panel Visual Progression Grid</h3>
                <div class="grid-container">
                    <img src="cid:grid_overview" alt="8-Panel Red Car Arrival Progression" />
                    <div class="img-caption">Chronological Progression (Top: 6:10 PM - 6:25 PM | Bottom: 6:27 PM Entry - 6:30 PM Parked)</div>
                </div>

                <h3 style="color: #0f172a; margin-top: 24px;">🔍 Close-Up Inspection Shots</h3>
                <div class="gallery">
                    <div class="gallery-item">
                        <img src="cid:shot_610" alt="6:10 PM Approach" />
                        <div class="gallery-label">1. 6:10:00 PM PDT (Initial Edge View)</div>
                    </div>
                    <div class="gallery-item">
                        <img src="cid:shot_625" alt="6:25 PM Position" />
                        <div class="gallery-label">2. 6:25:00 PM PDT (Positioned at Entrance)</div>
                    </div>
                    <div class="gallery-item">
                        <img src="cid:shot_627_18" alt="6:27:18 PM Entry" />
                        <div class="gallery-label">3. 6:27:18 PM PDT (🚗 Driving Forward into Garage)</div>
                    </div>
                    <div class="gallery-item">
                        <img src="cid:shot_630" alt="6:30 PM Parked" />
                        <div class="gallery-label">4. 6:30:00 PM PDT (🅿️ Fully Parked at Garage)</div>
                    </div>
                </div>
            </div>
            <div class="footer">
                Twitch Surveillance System &bull; Kitchen Channel 3 Analysis
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
    msg_root.attach(msg_alt)
    msg_alt.attach(MIMEText(html_body, "html"))
    
    # Attach grid
    if os.path.exists("kitchen_gallery_608_630/red_car_arrival_grid.jpg"):
        with open("kitchen_gallery_608_630/red_car_arrival_grid.jpg", "rb") as f:
            img = MIMEImage(f.read())
            img.add_header("Content-ID", "<grid_overview>")
            img.add_header("Content-Disposition", "inline", filename="red_car_arrival_grid.jpg")
            msg_root.attach(img)
            
    # Attach 4 key zoom shots
    shots_to_attach = [
        ("shot_610", "kitchen_timeline_608_630/v2837528327_zoom_10m00s.jpg"),
        ("shot_625", "kitchen_timeline_608_630/v2837541368_zoom_25m00s.jpg"),
        ("shot_627_18", "red_car_exact_arrival/v2837542994_627_PM_t18s.jpg"),
        ("shot_630", "kitchen_timeline_608_630/v2837545204_zoom_30m00s.jpg"),
    ]
    
    for cid, path in shots_to_attach:
        if os.path.exists(path):
            with open(path, "rb") as f:
                img = MIMEImage(f.read())
                img.add_header("Content-ID", f"<{cid}>")
                img.add_header("Content-Disposition", "inline", filename=f"{cid}.jpg")
                msg_root.attach(img)
                
    print(f"Connecting to Postmark SMTP {smtp_host}:{smtp_port}...")
    with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg_root)
    print(f"[SUCCESS] Multi-shot timeline report email sent to {to_addr} via Postmark!")

if __name__ == "__main__":
    send_email()
