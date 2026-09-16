#!/usr/bin/env python3
"""
Build the camera summary in GitHub Actions and publish it to Google Drive.

Why this exists: the house moved to a cable line with 2.9 Mbps upstream.
Uploading the analysis from the NAS costs hours of saturated upload a day. The
footage is already in the cloud - Twitch holds every VOD for 7 days - so a
runner can fetch it cloud-to-cloud, analyse it, and push the result to Drive
without touching the home connection at all.

The NAS keeps doing what only it can do: hold the year-long clip archive that
outlives Twitch's 7-day retention, and serve the LAN viewer.

State lives on Drive, not on the runner, because runners are disposable:

    state/vods_index.json            every VOD ever seen (survives expiry)
    daily/<day>/analysis.json        per-clip analysis cache

Both are pulled before the run and pushed after, so each run only decodes the
clips that appeared since the last one.
"""
import os
import re
import sys
import json
import time
import shutil
import datetime
import subprocess

CHANNEL = os.environ.get("TWITCH_CHANNEL", "elarathornfield168")
BASE = os.environ.get("ARCHIVE_BASE", os.path.abspath("archive"))
REMOTE = os.environ.get("RCLONE_REMOTE", "gdrive:camera_archive")
# How far back to look. Must exceed the gap between runs or footage falls
# straight through it: the workflow runs every 6 hours, so 7 gives an hour of
# overlap for a slow VOD or a late start.
WINDOW_H = float(os.environ.get("WINDOW_HOURS", "7"))

CLIPS = os.path.join(BASE, "clips")
DAILY = os.path.join(BASE, "daily")
STATE = os.path.join(BASE, "state")
# Must match what build_daily reads - it looks for exactly this name.
INDEX = os.path.join(STATE, "vods_index.json")

RCLONE_NET = ["--contimeout", "20s", "--timeout", "300s",
              "--low-level-retries", "3", "--retries", "2"]


def log(msg):
    print("%s  %s" % (datetime.datetime.now().strftime("%H:%M:%S"), msg),
          flush=True)


def run(cmd, **kw):
    return subprocess.run(cmd, **kw)


def rclone(args, quiet=False):
    r = run(["rclone"] + args + RCLONE_NET,
            stdout=subprocess.DEVNULL if quiet else None,
            stderr=subprocess.DEVNULL if quiet else None)
    return r.returncode


# ---------------------------------------------------------------- state ----

def pull_state(day):
    """Fetch the index and this day's analysis cache from Drive."""
    os.makedirs(STATE, exist_ok=True)
    os.makedirs(os.path.join(DAILY, day), exist_ok=True)
    rclone(["copy", "%s/state/vods_index.json" % REMOTE, STATE], quiet=True)
    # Only the cache and the small summary files - NOT activity/, which is
    # gigabytes and is never read back, only added to.
    rclone(["copy", "%s/daily/%s/analysis.json" % (REMOTE, day),
            os.path.join(DAILY, day)], quiet=True)
    rclone(["copy", "%s/daily/%s/summary" % (REMOTE, day),
            os.path.join(DAILY, day, "summary"),
            "--exclude", "thumbs/**"], quiet=True)
    have = os.path.exists(os.path.join(DAILY, day, "analysis.json"))
    log("state: index %s, %s cache %s"
        % ("yes" if os.path.exists(INDEX) else "none",
           day, "restored" if have else "none (first run for this day)"))


def drive_folder_id(day):
    """The day's Drive folder id, written out for the email step to link to.

    Only the id is recorded. Opening that URL still requires access to the
    account, so this shares nothing and makes nothing public.
    """
    r = run(["rclone", "lsjson", "--dirs-only", "%s/daily" % REMOTE]
            + RCLONE_NET, capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return ""
    try:
        for d in json.loads(r.stdout.decode("utf-8", "replace")):
            if d.get("Name") == day and d.get("ID"):
                path = os.path.join(STATE, "drive_folder_id.txt")
                with open(path, "w") as f:
                    f.write(d["ID"])
                return d["ID"]
    except Exception as e:
        log("could not read drive folder id: %s" % e)
    return ""


def push_state(day):
    rclone(["copy", INDEX, "%s/state" % REMOTE])
    rclone(["copy", os.path.join(DAILY, day), "%s/daily/%s" % (REMOTE, day),
            "--exclude", "live/**"])


# ---------------------------------------------------------------- twitch ---

def list_twitch():
    """Ask Twitch what VODs exist. Timestamps live in the thumbnail URL."""
    url = "https://www.twitch.tv/%s/videos?filter=all&sort=time" % CHANNEL
    out = run(["yt-dlp", "--flat-playlist", "--no-warnings", "-J", url],
              capture_output=True, text=True, timeout=1800)
    if out.returncode != 0:
        log("yt-dlp listing failed: %s" % (out.stderr or "")[:300])
        return []
    rows = []
    for e in json.loads(out.stdout).get("entries", []):
        m = re.search(r"_(\d{10})/", e.get("thumbnail") or "")
        if m:
            rows.append([int(m.group(1)), e["id"], e.get("duration") or 0,
                         e["url"]])
    return rows


def merge_index(new_rows):
    old = []
    if os.path.exists(INDEX):
        try:
            old = json.load(open(INDEX))
        except Exception:
            old = []
    by_id = {r[1]: r for r in old}
    added = sum(1 for r in new_rows if r[1] not in by_id)
    for r in new_rows:
        by_id.setdefault(r[1], r)
    rows = sorted(by_id.values(), key=lambda r: r[0])
    os.makedirs(STATE, exist_ok=True)
    json.dump(rows, open(INDEX, "w"))
    return rows, added


def download_window(rows, day):
    """Fetch VODs inside the window that are not already analysed."""
    cutoff = time.time() - WINDOW_H * 3600
    cache = {}
    try:
        cache = json.load(open(os.path.join(DAILY, day, "analysis.json")))
        cache = cache.get("clips") or {}
    except Exception:
        pass

    want = [(ts, vid, url) for ts, vid, _dur, url in rows
            if ts >= cutoff
            and datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d") == day
            and vid not in cache]
    if not want:
        log("no new VODs in the last %gh" % WINDOW_H)
        return 0

    out = os.path.join(CLIPS, day)
    os.makedirs(out, exist_ok=True)
    got = 0
    for _ts, vid, url in want:
        dst = os.path.join(out, vid + ".mp4")
        if os.path.exists(dst):
            continue
        r = run(["yt-dlp", "--no-warnings", "--no-progress", "-f", "best",
                 "-o", dst, url],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if r.returncode == 0 and os.path.exists(dst):
            got += 1
        else:
            log("  download failed: %s" % vid)
    log("downloaded %d of %d new VODs in the window" % (got, len(want)))
    return got


# ---------------------------------------------------------------- main -----

def main():
    day = os.environ.get("DAY") or datetime.date.today().strftime("%Y-%m-%d")
    log("=== summary job for %s (channel=%s, window=%gh) ==="
        % (day, CHANNEL, WINDOW_H))
    for d in (CLIPS, DAILY, STATE):
        os.makedirs(d, exist_ok=True)

    pull_state(day)

    rows, added = merge_index(list_twitch())
    log("index: %d VODs known (%d new)" % (len(rows), added))

    download_window(rows, day)

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    os.environ["ARCHIVE_BASE"] = BASE
    import build_daily
    build_daily.build_day(day)

    push_state(day)
    fid = drive_folder_id(day)
    log("=== published %s to %s/daily/%s%s ==="
        % (day, REMOTE, day, " (folder %s)" % fid if fid else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
