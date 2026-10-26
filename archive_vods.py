#!/usr/bin/env python3
"""Archive Twitch VODs to Google Drive, from inside GitHub Actions.

WHY THIS EXISTS
---------------
The footage archive used to be made on the QNAP: a container (`camera-live`)
ran ffmpeg against the Twitch live stream 24/7 and wrote 60-second segments
into /share/CACHEDEV1_DATA/camera_archive -- 886 GB and ~12 MB/min, on the
SAME thin pool (tp1) as rack1's mail LUN, behind a house line with 2.9 Mbps
upstream. So the archive competed for disk with the mail store and for uplink
with everything else.

Nothing about that work needs to happen at the house. Twitch already holds
every VOD for 7 days, and `summary_job.py` already works from that cloud copy
for exactly this reason (see its header). This script closes the one remaining
gap: `summary_job.py` caches ANALYSIS to Drive but never archives the FOOTAGE.

Run from a GitHub runner, both hops are cloud-to-cloud -- Twitch to the runner,
runner to Drive -- and the house uplink is never touched at all.

WHAT IT DOES
------------
  1. list the channel's VODs (yt-dlp, flat playlist -- no download)
  2. skip any already on Drive
  3. for each remaining one: download, `rclone moveto` it to Drive, delete
  4. record it in state/vods_archived.json on Drive

Layout on the remote (default gdrive:camera_archive):
    vods/<YYYY-MM-DD>/<vid>.mp4      the footage          <- new, this script
    state/vods_archived.json         what has been archived <- new, this script
    state/vods_index.json            summary_job.py's own index (NOT touched)
    daily/<day>/...                  summary_job.py's analysis cache (NOT touched)

`vods/` and `state/vods_archived.json` are deliberately separate names so this
can never race summary_job.py, which owns `daily/` and `state/vods_index.json`.

DELIBERATE DUPLICATION
----------------------
`check_recent_motion.py` already has `fetch_recent_videos()` and the
thumbnail-epoch trick, and this file repeats them rather than importing. That
module imports cv2 and numpy at module scope, so importing it would pull ~60 MB
of OpenCV into a job whose entire purpose is to move files. The listing logic
is ~25 lines; the dependency is not worth it. If the epoch regex ever changes
there, change it here too.
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

# America/Vancouver, not Los_Angeles, and not the runner's UTC. summary.yml
# spells out why: "The NAS and the stream workflow both use this zone; they
# must agree or they fight over the same Drive paths with different day
# boundaries." A UTC day would roll over at 17:00 local and file an evening
# VOD under tomorrow.
try:
    from zoneinfo import ZoneInfo
    PACIFIC = ZoneInfo(os.environ.get("TZ") or "America/Vancouver")
except Exception:                                    # pragma: no cover
    PACIFIC = timezone(timedelta(hours=-8))

CHANNEL = os.environ.get("TWITCH_CHANNEL", "elarathornfield168")
REMOTE = os.environ.get("RCLONE_REMOTE", "gdrive:camera_archive")
WORK = os.environ.get("WORK_DIR", "vod_staging")

# Twitch keeps VODs 7 days, so anything older is gone whatever we do. Looking
# back further than that only lengthens the listing for no gain.
LOOKBACK_HOURS = float(os.environ.get("LOOKBACK_HOURS", "26"))

# Stop before the runner's own limit so the last upload is never truncated.
# A partial file on Drive is worse than a missing one: the next run would see
# it present and skip it. SIZE_SLACK below is what guards against that.
BUDGET_SECONDS = int(os.environ.get("BUDGET_SECONDS", "2400"))

# Keep a floor of free disk. A 20-minute 1280x480 VOD is ~250 MB; the runner
# has ~14 GB. One at a time means this is never tight, but a pathological VOD
# must not fill the disk and break the upload of what already downloaded.
MIN_FREE_MB = int(os.environ.get("MIN_FREE_MB", "3000"))

# A remote file this much smaller than the local one is treated as a failed
# earlier upload and replaced rather than skipped.
SIZE_SLACK = 0.98

# 0 = keep everything. Set to a number of days to prune older footage from
# Drive -- at ~12 MB/min the archive grows ~17 GB/day, so a Drive plan will
# need either a lot of room or a retention window.
RETAIN_DAYS = int(os.environ.get("RETAIN_DAYS", "0"))

RCLONE_NET = ["--contimeout", "20s", "--timeout", "300s",
              "--low-level-retries", "4", "--retries", "3"]

START = time.time()


def log(msg):
    print("%s  %s" % (datetime.now(PACIFIC).strftime("%H:%M:%S"), msg), flush=True)


def budget_left():
    return BUDGET_SECONDS - (time.time() - START)


def free_mb(path="."):
    try:
        st = os.statvfs(path)
        return (st.f_bavail * st.f_frsize) // (1024 * 1024)
    except Exception:
        return 1 << 30


def rclone(args, capture=True):
    return subprocess.run(["rclone"] + args + RCLONE_NET,
                          capture_output=capture, text=True)


def pacific_day(epoch):
    return datetime.fromtimestamp(epoch, PACIFIC).strftime("%Y-%m-%d")


# ------------------------------------------------------------------ listing --

def list_vods():
    """Every VOD on the channel page, newest first, as (vid, epoch, title)."""
    res = subprocess.run([
        sys.executable, "-m", "yt_dlp",
        "--flat-playlist", "--dump-json", "--playlist-items", "1-400",
        "https://www.twitch.tv/%s/videos?filter=all&sort=time" % CHANNEL,
    ], capture_output=True, text=True)

    if not res.stdout.strip():
        log("yt-dlp returned no videos")
        if res.stderr:
            log("yt-dlp stderr: %s" % res.stderr.strip()[:300])
        return []

    out = []
    for line in res.stdout.strip().split("\n"):
        try:
            v = json.loads(line)
        except Exception:
            continue

        vid = v.get("id") or ""
        if not vid:
            continue

        # The true broadcast epoch is in the thumbnail URL -- the same trick
        # check_recent_motion.py uses, because `timestamp` is often absent on
        # a flat-playlist entry:
        #   ..._elarathornfield168_318630196567_1785176728//thumb/thumb0-...
        epoch = None
        m = re.search(r"_(\d{9,11})//?thumb", v.get("thumbnail") or "")
        if m:
            epoch = int(m.group(1))
        elif v.get("timestamp"):
            epoch = int(v["timestamp"])
        elif v.get("release_timestamp"):
            epoch = int(v["release_timestamp"])
        if epoch is None:
            continue

        out.append((vid if vid.startswith("v") else "v" + vid,
                    epoch, (v.get("title") or "").strip()))

    out.sort(key=lambda t: t[1], reverse=True)
    return out


# -------------------------------------------------------------------- state --

def pull_state():
    os.makedirs(WORK, exist_ok=True)
    rclone(["copy", "%s/state/vods_archived.json" % REMOTE, WORK])
    p = os.path.join(WORK, "vods_archived.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            log("state: %d VODs already archived" % len(d))
            return d
        except Exception:
            log("state file unreadable - starting a fresh index")
    else:
        log("state: no index on Drive yet")
    return {}


def push_state(state):
    p = os.path.join(WORK, "vods_archived.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1, sort_keys=True)
    r = rclone(["copy", p, "%s/state" % REMOTE])
    if r.returncode != 0:
        log("WARNING: could not push state: %s" % (r.stderr or "").strip()[:200])


def remote_sizes(day, vid):
    """Every size on Drive carrying this name. Idempotency does not rely on the
    state file: a lost index must not re-upload the whole week.

    Returns a LIST, not one size, because Google Drive keys files by id and
    happily holds several with the same name in one folder. That is not
    hypothetical here - clips/2026-09-16 has 51 files under 28 distinct names,
    one of them three times. A single-value lookup would pick whichever copy
    came back first and could call a truncated one complete.
    """
    r = rclone(["lsjson", "%s/vods/%s" % (REMOTE, day)])
    if r.returncode != 0:
        return []
    try:
        return [int(e.get("Size") or 0)
                for e in json.loads(r.stdout or "[]")
                if e.get("Name") == "%s.mp4" % vid]
    except Exception:
        return []


def drop_remote(day, vid):
    """Remove every copy of this name. --include scopes it to the one file, so
    this cannot touch anything else in the day folder."""
    rclone(["delete", "%s/vods/%s" % (REMOTE, day),
            "--include", "%s.mp4" % vid], capture=False)


# ----------------------------------------------------------------- transfer --

def download(vid):
    url = "https://www.twitch.tv/videos/%s" % vid.lstrip("v")
    local = os.path.join(WORK, "%s.mp4" % vid)
    if os.path.exists(local):
        os.remove(local)

    # Generous timeout: this is a full VOD, not the 120 s probe
    # check_recent_motion.py does. Capped by whatever budget remains.
    timeout = max(120, min(1500, int(budget_left()) - 120))
    try:
        subprocess.run([
            sys.executable, "-m", "yt_dlp",
            "--no-playlist", "--no-warnings", "--no-progress",
            "--retries", "5", "--fragment-retries", "10",
            "-o", local, url,
        ], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        log("  download timed out after %ds" % timeout)
        if os.path.exists(local):
            os.remove(local)
        return None

    if os.path.exists(local) and os.path.getsize(local) > 10240:
        return local
    if os.path.exists(local):
        os.remove(local)
    return None


def archive_one(vid, epoch, title, state):
    day = pacific_day(epoch)
    dest_dir = "%s/vods/%s" % (REMOTE, day)

    local = download(vid)
    if not local:
        log("  %s: download failed - leaving it for the next run" % vid)
        return False

    size = os.path.getsize(local)

    # Skip a single complete copy; replace anything else. Duplicates always
    # get cleared, because "which of these two is the good one" is not a
    # question worth carrying forward.
    sizes = remote_sizes(day, vid)
    if len(sizes) == 1 and sizes[0] >= size * SIZE_SLACK:
        log("  %s: already complete on Drive (%d MB) - skipping upload"
            % (vid, sizes[0] // (1024 * 1024)))
        os.remove(local)
        state[vid] = {"day": day, "size": sizes[0],
                      "archived_at": int(time.time()), "title": title}
        return True
    if sizes:
        log("  %s: clearing %d stale/duplicate copy(ies) on Drive %s"
            % (vid, len(sizes), [s // (1024 * 1024) for s in sizes]))
        drop_remote(day, vid)

    # moveto deletes the local copy only on a successful transfer.
    r = rclone(["moveto", local, "%s/%s.mp4" % (dest_dir, vid)], capture=False)
    if r.returncode != 0:
        log("  %s: upload FAILED (rc=%s) - local copy kept for retry"
            % (vid, r.returncode))
        return False

    log("  %s: archived %d MB -> vods/%s/" % (vid, size // (1024 * 1024), day))
    state[vid] = {"day": day, "size": size, "archived_at": int(time.time()),
                  "title": title}
    return True


# ---------------------------------------------------------------- retention --

def prune(state):
    if RETAIN_DAYS <= 0:
        return
    cutoff = (datetime.now(PACIFIC) - timedelta(days=RETAIN_DAYS)).strftime("%Y-%m-%d")
    r = rclone(["lsjson", "--dirs-only", "%s/vods" % REMOTE])
    if r.returncode != 0:
        return
    try:
        days = [e.get("Name") for e in json.loads(r.stdout or "[]")]
    except Exception:
        return
    for d in sorted(x for x in days if x and x < cutoff):
        log("prune: removing vods/%s (older than %d days)" % (d, RETAIN_DAYS))
        rclone(["purge", "%s/vods/%s" % (REMOTE, d)], capture=False)
        for vid, meta in list(state.items()):
            if meta.get("day") == d:
                del state[vid]


# --------------------------------------------------------------------- main --

def main():
    log("channel=%s remote=%s lookback=%.0fh budget=%ds"
        % (CHANNEL, REMOTE, LOOKBACK_HOURS, BUDGET_SECONDS))
    os.makedirs(WORK, exist_ok=True)

    if rclone(["listremotes"]).returncode != 0:
        log("ERROR: rclone is not configured in this job")
        return 1

    state = pull_state()
    vods = list_vods()
    if not vods:
        return 1
    log("channel lists %d VODs" % len(vods))

    floor = time.time() - LOOKBACK_HOURS * 3600
    todo = [(v, e, t) for (v, e, t) in vods if e >= floor and v not in state]
    log("%d within %.0fh and not yet archived" % (len(todo), LOOKBACK_HOURS))

    # Oldest first: Twitch expires VODs at 7 days, so the one closest to
    # falling off the end is the one worth securing first.
    todo.sort(key=lambda t: t[1])

    done = failed = 0
    try:
        for vid, epoch, title in todo:
            if budget_left() < 240:
                log("budget spent - %d left for the next run" % (len(todo) - done - failed))
                break
            if free_mb(WORK) < MIN_FREE_MB:
                log("only %d MB free - stopping before the disk fills" % free_mb(WORK))
                break
            log("%s (%s)" % (vid, pacific_day(epoch)))
            if archive_one(vid, epoch, title, state):
                done += 1
                push_state(state)       # after each, so a kill loses at most one
            else:
                failed += 1
        prune(state)
    finally:
        push_state(state)

    log("archived %d, failed %d, index holds %d" % (done, failed, len(state)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
