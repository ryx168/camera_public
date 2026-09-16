#!/usr/bin/env python3
"""
Email the camera summary after the Actions job has built it.

Replaces the per-incident email the old 3-hour motion check used to send. That
one mailed raw snapshots; this one mails the analysed result - what happened,
on which cameras, and a few thumbnails - with a link straight to the day's
Google Drive folder for the full footage.

Credentials come from the environment only. Nothing is defaulted to a real
value: this repo is public, and the existing send_motion_email.py has its
Postmark token hardcoded here, which is exactly what this avoids.

    SES_SMTP_HOST / SMTP_HOST      SES_SMTP_USER / SMTP_USERNAME
    SES_SMTP_PORT / SMTP_PORT      SES_SMTP_PASS / SMTP_PASSWORD
    SES_SMTP_FROM / SMTP_FROM      ALERT_TO      / SMTP_TO
"""
import os
import re
import csv
import sys
import json
import smtplib
import datetime
from collections import Counter
from email.message import EmailMessage
from email.utils import parseaddr, formataddr
from email.header import Header

BASE = os.environ.get("ARCHIVE_BASE", os.path.abspath("archive"))
MAX_THUMBS = int(os.environ.get("EMAIL_THUMBS", "6"))
ONLY_IF_INCIDENTS = os.environ.get("EMAIL_ONLY_IF_INCIDENTS", "0") == "1"


def env(*names):
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return None


def split_addr(value):
    """(header form, bare envelope address).

    parseaddr mishandles an unquoted non-ASCII display name - given
    "<CJK name> <a@b.com>" it returned a five-character mangled address - so
    take whatever is inside the angle brackets as authoritative. RFC 2047
    encoding belongs in the header; the envelope must be bare ASCII.
    """
    m = re.search(r"<([^>]+)>", value)
    if m:
        addr = m.group(1).strip()
        name = value[:m.start()].strip().strip('"').strip()
    else:
        name, addr = parseaddr(value)
        if not addr:
            addr, name = value.strip(), ""
    if not addr.isascii():
        raise ValueError("email address is not ASCII")
    if name and not name.isascii():
        return formataddr((str(Header(name, "utf-8")), addr)), addr
    return (formataddr((name, addr)) if name else addr), addr


def load(day):
    out = os.path.join(BASE, "daily", day)
    try:
        manifest = json.load(open(os.path.join(out, "manifest.json")))
    except Exception:
        manifest = {}
    events = []
    try:
        with open(os.path.join(out, "summary", "events.csv"),
                  newline="", encoding="utf-8") as f:
            events = list(csv.DictReader(f))
    except Exception:
        pass
    return manifest, events, out


def build_body(day, manifest, events, drive_id):
    per_cam = Counter(e["camera"] for e in events)
    lines = ["Camera summary for %s" % day, ""]
    if not events:
        lines.append("Nothing moved on any camera.")
    else:
        lines.append("%d activity clips across %d camera%s."
                     % (len(events), len(per_cam),
                        "" if len(per_cam) == 1 else "s"))
        lines.append("")
        for cam, n in per_cam.most_common():
            lines.append("  %-14s %d" % (cam, n))
        lines.append("")
        lines.append("Most recent:")
        for e in events[-8:]:
            t = (e.get("time") or "")[11:19]
            lines.append("  %s  %-14s %s px" % (t, e["camera"],
                                                e.get("motion_px", "?")))
    cams = manifest.get("cameras") or []
    if cams:
        lines += ["", "Cameras seen: %s" % ", ".join(cams)]
    if manifest.get("generated"):
        lines += ["", "Built %s" % manifest["generated"].replace("T", " ")]
    if drive_id:
        lines += ["",
                  "Full footage on Google Drive:",
                  "https://drive.google.com/drive/folders/%s" % drive_id]
    return "\n".join(lines) + "\n"


def pick_thumbs(out, events):
    """A few thumbnails from the most recent incidents."""
    tdir = os.path.join(out, "summary", "thumbs")
    picked = []
    for e in reversed(events):
        name = os.path.basename(e.get("file", "")).rsplit(".", 1)[0] + ".jpg"
        p = os.path.join(tdir, name)
        if os.path.exists(p) and p not in picked:
            picked.append(p)
        if len(picked) >= MAX_THUMBS:
            break
    return picked


def main():
    day = os.environ.get("DAY") or datetime.date.today().strftime("%Y-%m-%d")
    drive_id = os.environ.get("DRIVE_FOLDER_ID") or ""
    manifest, events, out = load(day)

    if ONLY_IF_INCIDENTS and not events:
        print("no incidents and EMAIL_ONLY_IF_INCIDENTS=1 - not sending")
        return 0

    host = env("SES_SMTP_HOST", "SMTP_HOST", "SMTP_SERVER")
    user = env("SES_SMTP_USER", "SMTP_USERNAME", "SMTP_USER")
    pw = env("SES_SMTP_PASS", "SMTP_PASSWORD", "SMTP_PASS")
    frm = env("SES_SMTP_FROM", "SMTP_FROM")
    to = env("ALERT_TO", "SMTP_TO")
    port = int(env("SES_SMTP_PORT", "SMTP_PORT") or 587)
    if not all([host, user, pw, frm, to]):
        print("::warning::SMTP not configured - summary email skipped")
        return 0

    from_hdr, from_env = split_addr(frm)
    rcpt_hdrs, rcpt_envs = [], []
    for part in str(to).split(","):
        if part.strip():
            h, e = split_addr(part.strip())
            rcpt_hdrs.append(h)
            rcpt_envs.append(e)

    msg = EmailMessage()
    msg["Subject"] = str(Header(
        "Camera summary %s: %d activity clip%s"
        % (day, len(events), "" if len(events) == 1 else "s"), "utf-8"))
    msg["From"] = from_hdr
    msg["To"] = ", ".join(rcpt_hdrs)
    msg.set_content(build_body(day, manifest, events, drive_id))

    for p in pick_thumbs(out, events):
        try:
            with open(p, "rb") as f:
                msg.add_attachment(f.read(), maintype="image", subtype="jpeg",
                                   filename=os.path.basename(p))
        except Exception as e:
            print("  could not attach %s: %s" % (os.path.basename(p), e))

    try:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, pw)
            s.sendmail(from_env, rcpt_envs, msg.as_string())
        print("summary email sent to %s" % ", ".join(rcpt_envs))
    except Exception as e:
        # Never fail the workflow over email: the report is already on Drive.
        print("::warning::summary email failed: %s" % e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
