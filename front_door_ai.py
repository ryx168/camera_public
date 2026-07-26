#!/usr/bin/env python3
"""
Camera AI Person Detection Service (Multi-Camera + Email Alerts)
Monitors camera streams (Front, Office, Kitchen, Balcony, Backyard),
detects people, logs events, saves annotated snapshot images,
and sends email alerts with snapshot images to harry@superesolutions.com.
"""

import os
import sys
import time
import json
import argparse
import datetime
import urllib.request
import urllib.parse
import subprocess
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from pathlib import Path

import cv2
import numpy as np


class MultiCameraPersonDetector:
    def __init__(
        self,
        cameras,
        check_interval=2.0,
        confidence_threshold=0.4,
        cooldown_seconds=30.0,
        save_snapshots=True,
        snapshot_dir="logs/camera_snapshots",
        log_file="logs/camera_ai.log",
        events_file="logs/camera_events.json",
        webhook_url=None,
        alert_command=None,
        email_to="harry@superesolutions.com",
        email_from=None,
        smtp_host=None,
        smtp_port=None,
        smtp_user=None,
        smtp_pass=None,
        enable_email=True,
    ):
        """
        cameras: dict of {name: url} e.g. {"Front": "http://...", "Office": "http://..."}
        """
        self.cameras = cameras
        self.check_interval = check_interval
        self.confidence_threshold = confidence_threshold
        self.cooldown_seconds = cooldown_seconds
        self.save_snapshots = save_snapshots
        self.snapshot_dir = Path(snapshot_dir)
        self.log_file = Path(log_file)
        self.events_file = Path(events_file)
        self.webhook_url = webhook_url
        self.alert_command = alert_command

        # Email alert configuration
        self.enable_email = enable_email
        self.email_to = email_to or os.environ.get("ALERT_EMAIL_TO", "harry@superesolutions.com")
        self.email_from = email_from or os.environ.get("ALERT_EMAIL_FROM", "harry@superesolutions.com")
        self.smtp_host = smtp_host or os.environ.get("SMTP_HOST", "smtp.postmarkapp.com")
        self.smtp_port = int(smtp_port or os.environ.get("SMTP_PORT", "587"))
        self.smtp_user = smtp_user or os.environ.get("SMTP_USER", "8f23463b-5db0-4bfb-9adc-fa13016656d2")
        self.smtp_pass = smtp_pass or os.environ.get("SMTP_PASS", "8f23463b-5db0-4bfb-9adc-fa13016656d2")

        # Track cooldown per camera
        self.last_detection_times = {name: 0 for name in cameras}

        # Ensure directory structures exist
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.events_file.parent.mkdir(parents=True, exist_ok=True)

        # Initialize HOG people detector
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

        cam_summary = ", ".join([f"{name} ({self.obfuscate_url(url)})" for name, url in cameras.items()])
        self.log(f"AI Person Detector initialized for cameras: {cam_summary}")
        self.log(f"Settings: check_interval={check_interval}s, confidence={confidence_threshold}, cooldown={cooldown_seconds}s")
        if self.enable_email:
            self.log(f"📧 Email alerts active -> Recipient: {self.email_to} (via {self.smtp_host}:{self.smtp_port})")

    def obfuscate_url(self, url):
        """Hide password in log outputs"""
        if "@" in url:
            prefix, rest = url.split("@", 1)
            if "//" in prefix:
                proto, creds = prefix.split("//", 1)
                return f"{proto}//***:***@{rest}"
        return url

    def log(self, message):
        """Append log entry to text log file and print to stdout"""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted = f"[{timestamp}] {message}"
        
        try:
            print(formatted, flush=True)
        except UnicodeEncodeError:
            clean_formatted = formatted.encode(sys.stdout.encoding or 'ascii', errors='replace').decode(sys.stdout.encoding or 'ascii')
            print(clean_formatted, flush=True)

        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(formatted + "\n")
        except Exception as e:
            print(f"Error writing to log file: {e}", file=sys.stderr)

    def record_event(self, camera_name, count, boxes, snapshot_path=None):
        """Record detection event to JSON file"""
        now = datetime.datetime.now()
        event_data = {
            "timestamp": now.isoformat(),
            "camera": camera_name,
            "people_count": count,
            "boxes": [list(map(int, b)) for b in boxes],
            "snapshot": str(snapshot_path) if snapshot_path else None,
        }

        for target_file in [self.events_file, Path("logs/front_door_events.json")]:
            events = []
            if target_file.exists() and target_file.stat().st_size > 0:
                try:
                    with open(target_file, "r", encoding="utf-8") as f:
                        events = json.load(f)
                except Exception:
                    events = []

            events.append(event_data)
            if len(events) > 500:
                events = events[-500:]

            try:
                with open(target_file, "w", encoding="utf-8") as f:
                    json.dump(events, f, indent=2)
            except Exception as e:
                self.log(f"⚠️ Failed to write event JSON ({target_file}): {e}")

    def send_email_alert(self, camera_name, count, snapshot_path):
        """Send email alert with attached snapshot image to recipient"""
        if not self.enable_email or not self.email_to:
            return

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subject = f"🚨 AI Camera Alert: Person Detected at [{camera_name}] Camera"

        msg = MIMEMultipart("related")
        msg["Subject"] = subject
        msg["From"] = self.email_from
        msg["To"] = self.email_to

        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
            <div style="background-color: #d9534f; color: white; padding: 15px; border-radius: 5px;">
                <h2 style="margin: 0;">🚨 AI Camera Person Detection Alert</h2>
            </div>
            <div style="padding: 15px; border: 1px solid #ddd; margin-top: 10px; border-radius: 5px;">
                <p><b>Camera Name:</b> {camera_name}</p>
                <p><b>People Count:</b> {count}</p>
                <p><b>Detection Time:</b> {now_str}</p>
                <p>An annotated snapshot captured from the camera feed is attached below.</p>
                {"<br><img src='cid:snapshot_image' style='max-width: 100%; border: 3px solid #d9534f; border-radius: 5px;' />" if snapshot_path and Path(snapshot_path).exists() else ""}
            </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(html_body, "html"))

        if snapshot_path and Path(snapshot_path).exists():
            try:
                with open(snapshot_path, "rb") as f:
                    img_data = f.read()

                img_part = MIMEImage(img_data, name=Path(snapshot_path).name)
                img_part.add_header("Content-ID", "<snapshot_image>")
                img_part.add_header("Content-Disposition", "inline", filename=Path(snapshot_path).name)
                msg.attach(img_part)
            except Exception as e:
                self.log(f"⚠️ Failed to attach snapshot image to email: {e}")

        try:
            self.log(f"📧 Sending email alert to {self.email_to} for [{camera_name}]...")
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_pass)
                server.send_message(msg)
            self.log(f"✅ Email alert successfully delivered to {self.email_to}")
        except Exception as e:
            self.log(f"⚠️ Failed to send email alert: {e}")

    def trigger_webhook(self, camera_name, count, snapshot_path):
        """Send JSON webhook if configured"""
        if not self.webhook_url:
            return

        payload = json.dumps({
            "event": "person_detected",
            "camera": camera_name,
            "count": count,
            "timestamp": datetime.datetime.now().isoformat(),
            "snapshot": str(snapshot_path) if snapshot_path else None
        }).encode("utf-8")

        req = urllib.request.Request(
            self.webhook_url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "CameraAI/1.0"}
        )

        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                self.log(f"🔔 Webhook notification sent for [{camera_name}] (status {response.status})")
        except Exception as e:
            self.log(f"⚠️ Webhook notification failed for [{camera_name}]: {e}")

    def trigger_command(self, camera_name, count, snapshot_path):
        """Run custom shell command if configured"""
        if not self.alert_command:
            return

        cmd = self.alert_command.format(
            camera=camera_name,
            count=count,
            snapshot=str(snapshot_path) if snapshot_path else "",
            timestamp=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        )

        try:
            self.log(f"🚀 Executing alert command for [{camera_name}]: {cmd}")
            subprocess.Popen(cmd, shell=True)
        except Exception as e:
            self.log(f"⚠️ Alert command execution failed for [{camera_name}]: {e}")

    def capture_frame(self, camera_url):
        """Capture single frame from stream URL via OpenCV VideoCapture"""
        cap = cv2.VideoCapture(camera_url)
        if not cap.isOpened():
            return None

        ret, frame = cap.read()
        cap.release()

        if ret and frame is not None and frame.size > 0:
            return frame
        return None

    def detect_people(self, frame):
        """
        Detect people in frame using HOG Descriptor + groupRectangles
        Returns: list of (x, y, w, h) bounding boxes and confidence score list
        """
        if frame is None:
            return [], []

        height, width = frame.shape[:2]
        target_width = 800
        scale = 1.0

        if width > target_width:
            scale = target_width / float(width)
            resized = cv2.resize(frame, (target_width, int(height * scale)))
        else:
            resized = frame

        rects, weights = self.hog.detectMultiScale(
            resized,
            winStride=(8, 8),
            padding=(8, 8),
            scale=1.05
        )

        boxes = []
        confidences = []

        for i, (x, y, w, h) in enumerate(rects):
            weight = weights[i] if i < len(weights) else 0.5
            if weight >= self.confidence_threshold:
                orig_x = int(x / scale)
                orig_y = int(y / scale)
                orig_w = int(w / scale)
                orig_h = int(h / scale)
                boxes.append((orig_x, orig_y, orig_w, orig_h))
                confidences.append(float(weight))

        if len(boxes) > 0:
            boxes_array = np.array([[x, y, x + w, y + h] for (x, y, w, h) in boxes])
            pick = cv2.groupRectangles(boxes_array.tolist(), groupThreshold=1, eps=0.2)
            filtered_boxes = []
            for rect in pick[0]:
                x1, y1, x2, y2 = rect
                filtered_boxes.append((x1, y1, x2 - x1, y2 - y1))
            boxes = filtered_boxes if len(filtered_boxes) > 0 else boxes

        return boxes, confidences

    def process_camera(self, camera_name, camera_url):
        """Capture frame, perform detection, log results and alert if cooldown passed for specific camera"""
        frame = self.capture_frame(camera_url)
        if frame is None:
            return False, 0

        boxes, weights = self.detect_people(frame)
        people_count = len(boxes)

        if people_count > 0:
            now = time.time()
            last_time = self.last_detection_times.get(camera_name, 0)
            time_since_last = now - last_time

            self.log(f"🚨 PERSON DETECTED at [{camera_name}] camera! Count: {people_count}")

            snapshot_path = None
            if self.save_snapshots:
                timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                snapshot_filename = f"{camera_name.lower()}_person_{timestamp_str}.jpg"
                snapshot_path = self.snapshot_dir / snapshot_filename

                annotated = frame.copy()
                for (x, y, w, h) in boxes:
                    cv2.rectangle(annotated, (x, y), (x + w, y + h), (0, 0, 255), 2)
                    cv2.putText(
                        annotated,
                        f"Person ({camera_name})",
                        (x, max(y - 10, 20)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (0, 0, 255),
                        2
                    )

                cv2.imwrite(str(snapshot_path), annotated)
                if camera_name == "Front":
                    alt_dir = Path("logs/front_door_snapshots")
                    alt_dir.mkdir(parents=True, exist_ok=True)
                    cv2.imwrite(str(alt_dir / f"front_door_person_{timestamp_str}.jpg"), annotated)

                self.log(f"📸 Saved snapshot: {snapshot_path}")

            # Record event log
            self.record_event(camera_name, people_count, boxes, snapshot_path)

            # Trigger alert actions if past cooldown
            if time_since_last >= self.cooldown_seconds:
                self.last_detection_times[camera_name] = now
                self.send_email_alert(camera_name, people_count, snapshot_path)
                self.trigger_webhook(camera_name, people_count, snapshot_path)
                self.trigger_command(camera_name, people_count, snapshot_path)
            else:
                self.log(f"⏳ Cooldown active for [{camera_name}] ({int(self.cooldown_seconds - time_since_last)}s remaining) - skipped alert.")

            return True, people_count

        return True, 0

    def run_continuous(self):
        """Run continuous monitoring loop across all configured cameras"""
        self.log("🚀 Starting AI Camera Person Monitoring loop...")
        try:
            while True:
                for name, url in self.cameras.items():
                    success, count = self.process_camera(name, url)
                    if not success:
                        pass
                time.sleep(self.check_interval)
        except KeyboardInterrupt:
            self.log("🛑 AI camera detector stopped by user.")


def main():
    parser = argparse.ArgumentParser(description="Multi-Camera AI Person Detection Service with Email Alerts")

    cam_pass = os.environ.get("CAM_PASS", "")

    # Default monitored cameras: All cameras (Front, Office, Kitchen, Balcony, Backyard)
    default_front = os.environ.get(
        "FRONT_CAM_URL",
        f"http://admin:{cam_pass}@192.168.1.38/video.cgi" if cam_pass else "http://192.168.1.38/video.cgi"
    )
    default_office = os.environ.get("OFFICE_CAM_URL", "http://192.168.1.31/video.cgi")
    default_kitchen = f"http://admin:{cam_pass}@192.168.1.33/video.cgi" if cam_pass else "http://192.168.1.33/video.cgi"
    default_balcony = f"http://admin:{cam_pass}@192.168.1.35/video.cgi" if cam_pass else "http://192.168.1.35/video.cgi"
    default_backyard = f"http://admin:{cam_pass}@192.168.1.39/video.cgi" if cam_pass else "http://192.168.1.39/video.cgi"

    parser.add_argument("--url", help="Override single camera stream URL")
    parser.add_argument("--name", default="Front", help="Single camera name (default: Front)")
    parser.add_argument("--cameras", default="Front,Office,Kitchen,Balcony,Backyard", help="Comma-separated list of cameras or 'all'")
    parser.add_argument("--interval", type=float, default=2.0, help="Check interval in seconds (default: 2.0)")
    parser.add_argument("--confidence", type=float, default=0.4, help="Detection confidence threshold (default: 0.4)")
    parser.add_argument("--cooldown", type=float, default=30.0, help="Alert cooldown in seconds (default: 30.0)")
    parser.add_argument("--no-snapshots", action="store_true", help="Disable saving snapshot images")
    parser.add_argument("--snapshot-dir", default="logs/camera_snapshots", help="Directory for snapshot images")
    parser.add_argument("--log-file", default="logs/camera_ai.log", help="Path to text log file")
    parser.add_argument("--events-file", default="logs/camera_events.json", help="Path to JSON events file")
    parser.add_argument("--email-to", default="harry@superesolutions.com", help="Recipient email address for person alert notifications")
    parser.add_argument("--no-email", action="store_true", help="Disable email alerts")
    parser.add_argument("--webhook", default=os.environ.get("ALERT_WEBHOOK_URL"), help="Webhook URL for alert notifications")
    parser.add_argument("--command", default=os.environ.get("ALERT_COMMAND"), help="Shell command to run on alert")
    parser.add_argument("--once", action="store_true", help="Run single frame check and exit")

    args = parser.parse_args()

    # Determine camera targets
    cameras = {}
    if args.url:
        cameras[args.name] = args.url
    else:
        cam_str = args.cameras.strip().lower()
        if cam_str == "all":
            cam_names = ["Front", "Office", "Kitchen", "Balcony", "Backyard"]
        else:
            cam_names = [c.strip() for c in args.cameras.split(",") if c.strip()]

        for c in cam_names:
            c_upper = c.capitalize()
            if c_upper == "Front":
                cameras["Front"] = default_front
            elif c_upper == "Office":
                cameras["Office"] = default_office
            elif c_upper == "Kitchen":
                cameras["Kitchen"] = default_kitchen
            elif c_upper == "Balcony":
                cameras["Balcony"] = default_balcony
            elif c_upper == "Backyard":
                cameras["Backyard"] = default_backyard

    if not cameras:
        cameras["Front"] = default_front
        cameras["Office"] = default_office

    detector = MultiCameraPersonDetector(
        cameras=cameras,
        check_interval=args.interval,
        confidence_threshold=args.confidence,
        cooldown_seconds=args.cooldown,
        save_snapshots=not args.no_snapshots,
        snapshot_dir=args.snapshot_dir,
        log_file=args.log_file,
        events_file=args.events_file,
        webhook_url=args.webhook,
        alert_command=args.command,
        email_to=args.email_to,
        enable_email=not args.no_email,
    )

    if args.once:
        all_ok = True
        for name, url in cameras.items():
            success, count = detector.process_camera(name, url)
            if not success:
                all_ok = False
        sys.exit(0 if all_ok else 1)
    else:
        detector.run_continuous()


if __name__ == "__main__":
    main()
