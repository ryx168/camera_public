#!/usr/bin/env python3
"""
Probe every camera at stream start and email if any cannot be reached.

This runs inside the GitHub Actions runner, over Tailscale, which is the same
path the stream itself uses - so it tests reachability as the stream will
actually experience it, not as the LAN sees it.

Never fails the workflow: a camera being down is news, not a reason to abandon
the recording of the ones that are up.

Credentials come from repository secrets only. This repo is public, so nothing
is defaulted to a real value here.

    SES_SMTP_HOST / SMTP_HOST       email-smtp.us-east-1.amazonaws.com
    SES_SMTP_PORT / SMTP_PORT       587
    SES_SMTP_USER / SMTP_USERNAME
    SES_SMTP_PASS / SMTP_PASSWORD
    SES_SMTP_FROM / SMTP_FROM
    ALERT_TO      / SMTP_TO
"""
import os
import sys
import smtplib
import subprocess
import datetime
from email.mime.text import MIMEText

CAM_PASS = os.environ.get("CAM_PASS", "")
WYZE_PASS = os.environ.get("WYZE_PASS", "")

# Same order and addresses as start-stream.sh, so the report matches the panes.
CAMERAS = [
    ("Office",       "http://192.168.1.31/video.cgi"),
    ("Front",        "http://admin:%s@192.168.1.38/video.cgi" % CAM_PASS),
    ("Kitchen",      "http://admin:%s@192.168.1.33/video.cgi" % CAM_PASS),
    ("Balcony",      "http://admin:%s@192.168.1.35/video.cgi" % CAM_PASS),
    ("Backyard",     "http://admin:%s@192.168.1.39/video.cgi" % CAM_PASS),
    ("Control Room", "rtsps://harry:%s@192.168.1.64:322/stream0" % WYZE_PASS),
]

TRIES = int(os.environ.get("CAMERA_PROBE_TRIES", "2"))


def redact(url):
    """Never put credentials in an email or a log line."""
    if "@" in url:
        scheme, rest = url.split("://", 1)
        return "%s://***@%s" % (scheme, rest.split("@", 1)[1])
    return url


def probe(url):
    extra = ["-rtsp_transport", "tcp"] if url.startswith("rtsp") else []
    limit = 15 if url.startswith("rtsp") else 12
    for attempt in range(TRIES):
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "quiet"] + extra +
                ["-analyzeduration", "2000000", "-probesize", "2000000",
                 "-i", url, "-show_entries", "format=duration"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=limit)
            if r.returncode == 0:
                return True
        except Exception:
            pass
    return False


def env(*names):
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return None


def send(offline, online):
    host = env("SES_SMTP_HOST", "SMTP_HOST", "SMTP_SERVER")
    user = env("SES_SMTP_USER", "SMTP_USERNAME", "SMTP_USER")
    pw = env("SES_SMTP_PASS", "SMTP_PASSWORD", "SMTP_PASS")
    frm = env("SES_SMTP_FROM", "SMTP_FROM")
    to = env("ALERT_TO", "SMTP_TO", "SES_SMTP_FROM", "SMTP_FROM")
    port = int(env("SES_SMTP_PORT", "SMTP_PORT") or 587)
    if not all([host, user, pw, frm, to]):
        print("::warning::SMTP not configured - cannot send offline alert")
        return

    when = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    body = (
        "Cameras unreachable when the stream started at %s.\n\n"
        "OFFLINE (%d):\n%s\n\nOnline (%d):\n%s\n\n"
        "Their panes are still composited, filled with a placeholder, so the\n"
        "mosaic layout does not change. They rejoin automatically on the next\n"
        "60-second segment once they answer.\n" % (
            when, len(offline),
            "\n".join("  - %s   %s" % (n, redact(u)) for n, u in offline),
            len(online),
            "\n".join("  - %s" % n for n, _ in online) or "  (none)"))

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = "Camera offline at stream start: %s" % ", ".join(
        n for n, _ in offline)
    msg["From"] = frm
    msg["To"] = to
    try:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, pw)
            s.sendmail(frm, [a.strip() for a in to.split(",")], msg.as_string())
        print("Offline alert sent to %s" % to)
    except Exception as e:
        print("::warning::offline alert failed to send: %s" % e)


def main():
    online, offline = [], []
    for name, url in CAMERAS:
        ok = probe(url)
        print("%s %-13s %s" % ("OK  " if ok else "DOWN", name, redact(url)))
        (online if ok else offline).append((name, url))

    print("\n%d/%d cameras reachable" % (len(online), len(CAMERAS)))
    if offline:
        send(offline, online)
    return 0            # never fail the stream over this


if __name__ == "__main__":
    sys.exit(main())
