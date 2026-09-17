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
# Which clips a run picks up.
#
# This used to be a look-back window in hours, and that is what emptied a whole
# day's page. The schedule asks for a run every 15 minutes; on 2026-09-17
# GitHub delivered four runs in nineteen hours:
#
#     01:04 -> 06:07 -> 11:38 -> 15:42 UTC
#
# Against a 2-hour window, only 8 of those 19 hours were ever looked at. The
# footage was fine - it simply fell between the windows, and nothing ever went
# back for it.
#
# Widening the window only moves the cliff: any fixed number can be exceeded by
# a long enough outage, and when it is, that footage is lost for good. So the
# question is no longer "what happened in the last N hours" (a clock, which can
# be wrong) but "what have I not analysed yet" (a fact, which cannot). Every
# VOD for the day that is missing from the cache is fetched, however old, so an
# outage of any length heals itself on the next run.
#
# WINDOW_HOURS remains as an optional limiter for a deliberately narrow manual
# run. Blank - the default - means the whole day.
_win = os.environ.get("WINDOW_HOURS", "").strip()
WINDOW_H = float(_win) if _win else 0.0

# The only thing a run really must not do is exceed the job timeout. A backlog
# is bounded per run instead of by age: 258 clips took 30 minutes to fetch, so
# this leaves room inside the 90-minute cap. Anything deferred is not lost - it
# is still missing from the cache, so the next run is what picks it up.
MAX_CLIPS = int(os.environ.get("MAX_CLIPS", "300"))

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


def activity_ids(day):
    """Map each activity clip to its Drive file id, so a card can link to it.

    Only ids are recorded. Opening one still needs access to the account, so
    the summary can be public while the footage stays behind the login.
    """
    r = run(["rclone", "lsjson", "%s/daily/%s/activity" % (REMOTE, day)]
            + RCLONE_NET, capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return 0
    try:
        rows = json.loads(r.stdout.decode("utf-8", "replace"))
        ids = {d["Name"]: d["ID"] for d in rows
               if not d.get("IsDir") and d.get("ID")}
        if not ids:
            return 0
        dst = os.path.join(DAILY, day, "summary", "activity_ids.json")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        json.dump(ids, open(dst, "w"))
        return len(ids)
    except Exception as e:
        log("could not map activity ids: %s" % e)
        return 0


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
    """Fetch every VOD of this day that has not been analysed yet."""
    cutoff = time.time() - WINDOW_H * 3600 if WINDOW_H else 0
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
        log("nothing unanalysed for %s - %d clips already cached"
            % (day, len(cache)))
        return 0

    want.sort()
    if len(want) > MAX_CLIPS:
        # Newest first: the top of the page should be current even while a
        # backlog is still draining. The rest stay uncached and are picked up
        # by the following run, so nothing is dropped.
        log("backlog of %d clips - taking the newest %d, the rest follow on "
            "the next run" % (len(want), MAX_CLIPS))
        want = want[-MAX_CLIPS:]
    log("%d clip%s to fetch for %s (%d already analysed)"
        % (len(want), "" if len(want) == 1 else "s", day, len(cache)))

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
    log("downloaded %d of %d clips" % (got, len(want)))
    return got


def write_step_summary(day, fid):
    """Put the digest on the run page itself.

    GitHub renders $GITHUB_STEP_SUMMARY as Markdown right on the run, so the
    result is readable without downloading anything. It strips data: URIs, so
    the thumbnails cannot come along - those are in the artifact and on Drive.
    """
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    import csv as _csv
    from collections import Counter
    out = os.path.join(DAILY, day, "summary")
    rows = []
    try:
        with open(os.path.join(out, "events.csv"), newline="",
                  encoding="utf-8") as f:
            rows = list(_csv.DictReader(f))
    except Exception:
        pass
    per_cam = Counter(r["camera"] for r in rows)

    md = ["## Camera summary %s" % day, ""]
    if not rows:
        md.append("Nothing moved on any camera.")
    else:
        md += ["**%d activity clips** across %d camera%s."
               % (len(rows), len(per_cam), "" if len(per_cam) == 1 else "s"),
               "", "| Camera | Clips |", "|---|---:|"]
        md += ["| %s | %d |" % (c, n) for c, n in per_cam.most_common()]
        md += ["", "### Most recent", "", "| Time | Camera | Motion |",
               "|---|---|---:|"]
        md += ["| %s | %s | %s |" % ((r.get("time") or "")[11:19], r["camera"],
                                     r.get("motion_px", "?"))
               for r in rows[-8:]]
    if fid:
        md += ["", "[Open this day on Google Drive]"
                   "(https://drive.google.com/drive/folders/%s)" % fid]
    md += ["", "_The full page is in the **summary-page** artifact below - "
               "download and open it; it is self-contained._"]
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(md) + "\n")
    except Exception as e:
        log("could not write the step summary: %s" % e)


# ---------------------------------------------------------------- main -----

def main():
    day = os.environ.get("DAY") or datetime.date.today().strftime("%Y-%m-%d")
    log("=== summary job for %s (channel=%s, scope=%s) ==="
        % (day, CHANNEL,
           "last %gh" % WINDOW_H if WINDOW_H else "whole day, uncached only"))
    for d in (CLIPS, DAILY, STATE):
        os.makedirs(d, exist_ok=True)

    pull_state(day)

    if os.environ.get("REBUILD") == "1":
        # Discard the cache and analyse the day again. Needed when cached
        # values are wrong rather than merely stale - the content timestamps
        # written while the runner was on UTC are epochs, seven hours out and
        # impossible to correct in place, and entries inherited from the NAS
        # reference thumbnails that were never uploaded.
        cache = os.path.join(DAILY, day, "analysis.json")
        if os.path.exists(cache):
            os.remove(cache)
        rclone(["delete", "%s/daily/%s/analysis.json" % (REMOTE, day)],
               quiet=True)
        log("rebuild: cache discarded, analysing %s from scratch" % day)

    rows, added = merge_index(list_twitch())
    log("index: %d VODs known (%d new)" % (len(rows), added))

    download_window(rows, day)

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    os.environ["ARCHIVE_BASE"] = BASE
    import build_daily
    build_daily.build_day(day)

    push_state(day)
    fid = drive_folder_id(day)

    # Drive will not render HTML, so also fold the day into one file with the
    # stylesheet and every thumbnail inlined. That one downloads from Drive and
    # opens anywhere, with no NAS and no network. Built after the first push so
    # it can carry a link to the folder it now lives in; the second push only
    # carries that new file.
    try:
        # The working pull skips thumbs/ because the analysis never reads them
        # back - but the standalone page must embed every one, and the runner
        # only has the handful it just produced. Fetch the rest now, or the
        # page ships with broken images (measured: 2 embedded, 61 missing).
        rclone(["copy", "%s/daily/%s/summary/thumbs" % (REMOTE, day),
                os.path.join(DAILY, day, "summary", "thumbs")], quiet=True)
        n = activity_ids(day)
        log("activity clips on Drive: %d" % n)
        import standalone
        if standalone.build(day, fid):
            push_state(day)
    except Exception as e:
        log("standalone page failed (report is already published): %s" % e)

    write_step_summary(day, fid)
    log("=== published %s to %s/daily/%s%s ==="
        % (day, REMOTE, day, " (folder %s)" % fid if fid else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
