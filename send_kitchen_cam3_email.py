#!/usr/bin/env python3
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

def send_kitchen_email():
    from_addr = "harry@superesolutions.com"
    to_addr = "harry@superesolutions.com"
    
    smtp_host = "smtp.postmarkapp.com"
    smtp_port = 587
    smtp_user = "8f23463b-5db0-4bfb-9adc-fa13016656d2"
    smtp_pass = "8f23463b-5db0-4bfb-9adc-fa13016656d2"
    
    subject = "🚨 Kitchen Camera (Cam 3) Verification: Red Car at Garage Entrance (6:10 PM PDT)"
    
    html_body = """<!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b; background-color: #f8fafc; margin: 0; padding: 20px; }
            .card { background: #ffffff; border-radius: 12px; max-width: 700px; margin: 0 auto; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.08); border: 1px solid #e2e8f0; }
            .header { background: linear-gradient(135deg, #b91c1c, #991b1b); color: #ffffff; padding: 24px; text-align: center; }
            .header h1 { margin: 0 0 6px 0; font-size: 22px; font-weight: 700; }
            .header p { margin: 0; font-size: 13px; opacity: 0.9; }
            .content { padding: 24px; }
            .badge { display: inline-block; padding: 4px 10px; border-radius: 9999px; font-size: 12px; font-weight: 600; text-transform: uppercase; }
            .badge-alert { background: #fee2e2; color: #991b1b; }
            .badge-success { background: #dcfce7; color: #166534; }
            .table-box { width: 100%; border-collapse: collapse; margin: 16px 0; }
            .table-box th, .table-box td { padding: 10px 12px; border: 1px solid #e2e8f0; font-size: 13px; text-align: left; }
            .table-box th { background-color: #f1f5f9; color: #475569; font-weight: 600; }
            .img-container { margin: 16px 0; text-align: center; background: #0f172a; border-radius: 8px; padding: 12px; }
            .img-container img { max-width: 100%; height: auto; border-radius: 6px; }
            .img-caption { color: #94a3b8; font-size: 12px; margin-top: 8px; font-weight: 500; }
            .footer { background-color: #f1f5f9; padding: 14px; text-align: center; font-size: 12px; color: #64748b; border-top: 1px solid #e2e8f0; }
        </style>
    </head>
    <body>
        <div class="card">
            <div class="header">
                <h1>Kitchen Camera (Cam 3) Verification Report</h1>
                <p>Target Object: Red Car / Garage Entry &bull; Time: 6:10 PM PDT (VOD: v2837528327)</p>
            </div>
            <div class="content">
                <p>Hello Harry,</p>
                <p>As requested, we focused the detailed analysis directly on the <strong>Third Camera (labeled "Kitchen", top-right view)</strong> at <strong>6:10 PM PDT</strong>.</p>
                
                <h3 style="color: #0f172a; margin-top: 20px;">📸 Kitchen Camera (Cam 3) Findings</h3>
                <p>In the Kitchen camera feed overlooking the deck/driveway and garage area, the <strong>red car</strong> is clearly identified in the lower-left region of the frame entering / positioned at the garage entrance.</p>

                <table class="table-box">
                    <tr>
                        <th>Camera Channel</th>
                        <th>Timestamp (PDT)</th>
                        <th>VOD Identifier</th>
                        <th>Visual Observation</th>
                    </tr>
                    <tr>
                        <td><strong>Cam 3 (Kitchen)</strong></td>
                        <td><strong>6:10:07 PM</strong></td>
                        <td><code>v2837528327</code></td>
                        <td><span class="badge badge-alert">Red Car Confirmed</span> Lower-left garage/driveway area</td>
                    </tr>
                </table>

                <div class="img-container">
                    <img src="cid:kitchen_full" alt="Kitchen Full Camera at 6:10 PM" />
                    <div class="img-caption">Kitchen Camera (Cam 3) Full Frame at 6:10 PM PDT</div>
                </div>

                <div class="img-container">
                    <img src="cid:kitchen_zoom" alt="Kitchen Red Car Zoom at 6:10 PM" />
                    <div class="img-caption">Zoomed View: Red Car at Lower-Left Garage / Driveway Entrance (6:10 PM PDT)</div>
                </div>

                <p style="font-size: 13px; color: #475569; margin-top: 16px;">
                    This confirms the vehicle identification specifically through the Kitchen camera channel.
                </p>
            </div>
            <div class="footer">
                Twitch Stream AI Surveillance System &bull; Kitchen Camera Channel 3
            </div>
        </div>
    </body>
    </html>
    """
    
    msg_root = MIMEMultipart("mixed")
    msg_root["Subject"] = subject
    msg_root["From"] = from_addr
    msg_root["To"] = to_addr
    
    msg_alternative = MIMEMultipart("alternative")
    msg_root.attach(msg_alternative)
    msg_alternative.attach(MIMEText(html_body, "html"))
    
    # Attach Kitchen Cam 3 images
    img1_path = "kitchen_red_car_zooms/v2837528327_full_kitchen.jpg"
    img2_path = "kitchen_red_car_zooms/v2837528327_zoom_corner.jpg"
    
    if os.path.exists(img1_path):
        with open(img1_path, "rb") as f:
            img1 = MIMEImage(f.read())
            img1.add_header("Content-ID", "<kitchen_full>")
            img1.add_header("Content-Disposition", "inline", filename="kitchen_full_610pm.jpg")
            msg_root.attach(img1)
            
    if os.path.exists(img2_path):
        with open(img2_path, "rb") as f:
            img2 = MIMEImage(f.read())
            img2.add_header("Content-ID", "<kitchen_zoom>")
            img2.add_header("Content-Disposition", "inline", filename="kitchen_red_car_zoom_610pm.jpg")
            msg_root.attach(img2)
            
    print(f"Connecting to Postmark SMTP {smtp_host}:{smtp_port}...")
    with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg_root)
    print(f"[SUCCESS] Kitchen Cam 3 verification report email sent to {to_addr} via Postmark!")

if __name__ == "__main__":
    send_kitchen_email()
