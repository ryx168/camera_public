#!/usr/bin/env python3
"""
Build a daily summary folder + activity clips from archived Twitch clips.

Written for a person scanning a day at a glance, not for a log reader. Raw
clips are grouped into *incidents* (a person crossing the garden makes eight
20-second clips but is one event), each incident gets a thumbnail cropped to
the camera that saw it, and the page leads with a plain-language headline.

Layout: the stream mosaic is 1280x480, a 3x2 grid of 426x240 cells in
CAMERA_ORDER. Cells that stay uniformly dark across the sampled frames are
treated as unused (fewer cameras were online that day) and skipped, so a day
recorded with four cameras does not produce phantom events for empty panes.
"""
import os
import re
import sys
import json
import csv
import html
import hashlib
import shutil
import datetime
from collections import defaultdict

import numpy as np
import cv2

# Runs both on the Windows workstation and inside the NAS container, and a
# container started before ARCHIVE_BASE existed must not fall back to a Windows
# path, so probe for the container mount first.
BASE = os.environ.get(
    "ARCHIVE_BASE",
    "/archive" if os.path.isdir("/archive") else r"C:/camera_archive")
CAMS = ["Office", "Front", "Kitchen", "Balcony", "Backyard",
        "Control Room"]
COLS, ROWS = 3, 2
SAMPLE_FPS = 2.0     # frames sampled per second of clip
BURST_FRAMES = int(os.environ.get("BURST_FRAMES", "4"))
SAMPLE_FRAMES = int(os.environ.get("SAMPLE_FRAMES", "24"))
# Changed pixels within a cell to count as motion. Measured baseline on real
# footage: median quiet cell is ~60px, p75 ~440, p95 ~3000. 3000 sits just
# above the noise floor, so it catches genuine movement without flagging
# compression churn and moving foliage on every clip.
MOTION_PX = int(os.environ.get("MOTION_PX", "3000"))
DIFF_THRESH = 28     # per-pixel delta that counts as changed
DEAD_STD = 6.0       # a cell this flat across samples is an unused pane

# The stream fills an absent camera's pane with a flat 0x141414 tile - luma 20.
# It is not perfectly flat: it carries the burnt-in camera label, so it measures
# std 6.3-6.6 and slipped straight past a std < 6 test, which is how a camera
# dropping out kept producing incidents with a black cover image. Identify it
# by what it actually is - near-black AND almost no structure. Genuine night
# footage is nowhere near: overnight panes measured mean 42-81 with std 41-50,
# so this cannot silence real dark-hours events.
# Clock OCR: 0 disables it entirely (times fall back to when the clip was
# pulled), OCR_EVERY is how often to take an anchor.
OCR_CLOCK = os.environ.get("OCR_CLOCK", "1") != "0"
OCR_EVERY = max(1, int(os.environ.get("OCR_EVERY", "10")))
LAYOUT_PROBE_FRAMES = int(os.environ.get("LAYOUT_PROBE_FRAMES", "1"))
PUBLISH_PARTIAL = os.environ.get("PUBLISH_PARTIAL", "0") == "1"
# Analyse only the last N hours of today, rather than re-decoding the whole
# day on every run. A full pass over ~1400 clips is roughly three hours on the
# NAS, which blocks collection the entire time; the hours anyone actually
# wants are the ones that just happened. 0 means no window (whole day), which
# is what past days still get. Hours outside the window keep whatever the last
# complete build produced - see events_base.csv in publish().
RECENT_HOURS = int(os.environ.get("RECENT_HOURS", "6"))
PLACEHOLDER_MEAN = float(os.environ.get("PLACEHOLDER_MEAN", "32"))
PLACEHOLDER_STD = float(os.environ.get("PLACEHOLDER_STD", "15"))
# Clips on one camera closer together than this belong to the same incident.
INCIDENT_GAP_S = int(os.environ.get("INCIDENT_GAP", "150"))
THUMB_W = 420
CHANNEL = os.environ.get("TWITCH_CHANNEL", "elarathornfield168")


def slug(cam):
    """Filename-safe camera token. Display names may contain spaces
    ("Control Room"); the files they generate must not, or the links in the
    summary pages need escaping everywhere they appear."""
    return cam.replace(" ", "")


# Reporting granularity, in minutes. 30 was tried, reverted to 60 because it
# doubled the number of layout detections, and is back now that detection is
# ~8x cheaper (pane origins are memoised) and a slot that cannot be read
# borrows from its neighbour instead of re-sweeping. The key is the slot's
# start as HHMM ("0700", "0730") so it sorts lexically, anchors cleanly and
# names its own page; the label is what the reader sees. Slots are derived at
# render time, so changing this needs no re-analysis - just a re-publish.
SLOT_MIN = int(os.environ.get("SLOT_MINUTES", "30"))


def slot_key(ts):
    return "%02d%02d" % (ts.hour, (ts.minute // SLOT_MIN) * SLOT_MIN)


def slot_label(key):
    return "%s:%s" % (key[:2], key[2:])


def slot_end_label(key):
    """Last minute of the slot, for 'between X and Y' headlines."""
    m = int(key[:2]) * 60 + int(key[2:]) + SLOT_MIN - 1
    return "%02d:%02d" % ((m // 60) % 24, m % 60)


def all_slots():
    return ["%02d%02d" % (h, m)
            for h in range(24) for m in range(0, 60, SLOT_MIN)]


# The stream composites however many cameras are online into one of six fixed
# layouts (see start-stream.sh). Pane position therefore does NOT identify a
# camera: with three online, the bottom pane is full width; with six it is a
# 3x2 grid. Geometry is (x, y, w, h) against the 1280x480 mosaic.
LAYOUTS = {
    1: [(0, 0, 1280, 480)],
    2: [(0, 0, 640, 480), (640, 0, 640, 480)],
    3: [(0, 0, 640, 240), (640, 0, 640, 240), (0, 240, 1280, 240)],
    4: [(0, 0, 640, 240), (640, 0, 640, 240),
        (0, 240, 640, 240), (640, 240, 640, 240)],
    5: [(0, 0, 426, 240), (426, 0, 426, 240), (852, 0, 426, 240),
        (0, 240, 640, 240), (640, 240, 640, 240)],
    6: [(0, 0, 426, 240), (426, 0, 426, 240), (852, 0, 426, 240),
        (0, 240, 426, 240), (426, 240, 426, 240), (852, 240, 426, 240)],
}
_CAM_LOOKUP = {c.lower().replace(" ", ""): c for c in CAMS}


# Footage captured before the rename carries the old burnt-in label, and no
# amount of renaming changes pixels already recorded.
_ALIASES = {"basement": "Control Room"}


def _read_label(frame, box):
    """OCR the camera name ffmpeg draws at the top-left of a pane.

    The label is white text on a 50%-opaque black box, so over bright
    backgrounds (foliage, sky) a single threshold loses it entirely. Several
    binarisations are tried and the first that yields a known name wins.
    """
    try:
        import pytesseract
    except ImportError:
        return None
    x, y, w, h = box
    crop = frame[y + 1:y + 26, x + 1:x + min(w, 230)]
    if crop.size == 0:
        return None
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)

    variants = []
    _, otsu = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(otsu)
    variants.append(cv2.bitwise_not(otsu))
    # Otsu handles the normal case; the fixed thresholds are the fallback for
    # a label sitting over very bright or very dark video. Trimming these to
    # two was measurably cheaper and measurably wrong - a clip that detected
    # six panes started detecting none - so they stay.
    for thr in (90, 120, 150, 180, 210):
        _, im = cv2.threshold(g, thr, 255, cv2.THRESH_BINARY)
        variants.append(im)

    known = list(_CAM_LOOKUP.items()) + list(_ALIASES.items())
    for im in variants:
        try:
            txt = pytesseract.image_to_string(im, config="--psm 7")
        except Exception:
            return None
        key = "".join(ch for ch in txt if ch.isalpha()).lower()
        if len(key) < 4:
            continue
        for k, name in known:
            if key.startswith(k[:5]):
                return name
    return None


def detect_layout(frame):
    """Return (n_panes, [camera names]) by reading the burnt-in labels.

    Scores each candidate layout by how many panes yield a known camera name,
    so a wrong pane count scores poorly and loses.
    """
    # The six candidate layouts share their pane corners: across all of them
    # there are only eight distinct (x, y) origins, and every crop clamps to
    # the same 230px width, so the same corner was being OCR'd up to four
    # times per frame. Read each origin once. 21 pane reads become 8, with
    # identical results.
    seen = {}

    def label(box):
        key = box[0], box[1]
        if key not in seen:
            seen[key] = _read_label(frame, box)
        return seen[key]

    best = (0, None, None)
    for i, n in enumerate(sorted(LAYOUTS, reverse=True)):  # richest first
        names = [label(b) for b in LAYOUTS[n]]
        hits = sum(1 for x in names if x)
        if i == 0 and hits == 0:
            # Not one pane of the richest layout produced a name. Every other
            # candidate also has a pane at (0, 0), which just failed, so none
            # of them can do better - this frame simply has no readable
            # labels. Sweeping the remaining five cost a failed detection more
            # than a successful one.
            return None, None
        # Every pane must resolve to a distinct camera. A duplicate means this
        # candidate is slicing one camera across several panes, which is the
        # signature of guessing the wrong pane count.
        if hits == n and len(set(names)) == n:
            # Stop here. Candidates are tried richest first and the test below
            # is `hits > best[0]` with hits <= n, so nothing smaller can ever
            # beat a perfect match - yet the sweep used to run all six anyway.
            # At seven binarisations per pane and ~1.2s a call, those wasted
            # candidates measured 170 SECONDS per clip, which is what made a
            # day's rebuild take hours.
            if n > 1:
                return n, names
            if hits > best[0]:
                best = (hits, n, names)
    if best[1] and best[1] > 1:
        return best[1], best[2]
    return None, None


def cell_box(w, h, idx):
    cw, ch = w // COLS, h // ROWS
    r, c = divmod(idx, COLS)
    return c * cw, r * ch, cw, ch


_TS_RE = re.compile(
    r"(20\d{2})[-/. ](\d{2})[-/. ](\d{2})\D{0,3}(\d{2})\D?(\d{2})\D?(\d{2})")


def read_burnt_time(frame):
    """The wall-clock the camera burns into the top-left pane, or None.

    A clip's filename records when it was pulled off Twitch, not when it was
    filmed. The broadcast runs behind - measured at 19 to 50 minutes on one
    day, and drifting as the push queue drains - so filing by the pull time
    puts events in the wrong slot entirely. The picture carries the truth: the
    D-Link draws 'YYYY-MM-DD HH:MM:SS' across the top of its pane, and the
    label ffmpeg adds sits on the same line.
    """
    try:
        import pytesseract
    except Exception:
        return None
    strip = frame[0:26, 0:340]
    if strip.size == 0:
        return None
    g = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, (g.shape[1] * 4, g.shape[0] * 4),
                   interpolation=cv2.INTER_CUBIC)
    # White-on-dark overlay, but it sits over live video, so one threshold is
    # not enough - the same problem _read_label has with the camera name.
    # tesseract costs 2.6-6s a call on the NAS, so this runs exactly one.
    # Measured on the same frame: 4x + digit whitelist 2.6s, 4x plain 4.4s,
    # 3x either way ~5.9s. The whitelist drops the space between date and
    # time, which _TS_RE already tolerates.
    variants = (cv2.threshold(g, 150, 255, cv2.THRESH_BINARY)[1],)
    for img in variants:
        try:
            txt = pytesseract.image_to_string(
                255 - img,
                config="--psm 7 -c tessedit_char_whitelist=0123456789-: ")
        except Exception:
            return None
        m = _TS_RE.search(txt.replace("O", "0").replace("l", "1"))
        if m:
            try:
                return datetime.datetime(*[int(x) for x in m.groups()])
            except ValueError:
                continue
    return None


def _clock_near(frames, idx):
    """Burnt-in time at one end of the clip, stepping inwards on failure.

    The overlay sits over live video, so any single frame can defeat OCR.
    """
    n = len(frames)
    step = 1 if idx == 0 else -1
    for k in range(2):
        j = idx + step * k
        if 0 <= j < n:
            t = read_burnt_time(frames[j])
            if t:
                return t
    return None


def _offset_at(known, ts):
    """Pull-to-film offset at `ts`, interpolated from the clips that did read.

    The offset drifts slowly, so a neighbour's offset is a far better estimate
    than assuming none at all - which would scatter unreadable clips by up to
    an hour.
    """
    if not known:
        return 0
    lo = None
    for kts, off in known:
        if kts <= ts:
            lo = (kts, off)
        else:
            if lo is None:
                return off
            span = kts - lo[0]
            if span <= 0:
                return lo[1]
            f = (ts - lo[0]) / float(span)
            return int(round(lo[1] + f * (off - lo[1])))
    return lo[1] if lo else 0


def _event_time(rec, ci, fallback):
    """Time of the frame where this camera's motion peaked.

    Interpolated across the clip's measured span. With no span to work from
    (the clock could not be read at both ends) the clip's own time stands.
    """
    a, b = rec.get("cts"), rec.get("cte")
    peaks, nf = rec.get("p") or [], rec.get("nf") or 0
    if not a or not b or b <= a or nf < 2 or ci >= len(peaks):
        return fallback
    f = min(max(peaks[ci], 0), nf - 1) / float(nf - 1)
    return datetime.datetime.fromtimestamp(a + (b - a) * f)


def apply_content_times(cc):
    """Give every clip an effective time: when it was filmed, not pulled."""
    known = sorted((r["ts"], r["cts"] - r["ts"]) for r in cc.values()
                   if r.get("ts") and r.get("cts"))
    read_ok = len(known)
    for r in cc.values():
        if r.get("dup") or r.get("bad") or not r.get("ts"):
            continue
        r["ets"] = r["cts"] if r.get("cts") else r["ts"] + _offset_at(
            known, r["ts"])
    return read_ok


def clip_time(vid, idx):
    """When a clip was recorded.

    Two sources now feed the archive. Twitch VODs carry their timestamp in the
    index built from thumbnail URLs. Segments from the live recorder have no
    VOD id at all - their wall-clock time is in the filename, which is exactly
    why the recorder writes it there.
    """
    if vid.startswith("live-"):
        try:
            return datetime.datetime.strptime(vid[5:], "%Y%m%d-%H%M%S")
        except ValueError:
            return None
    meta = idx.get(vid)
    return datetime.datetime.fromtimestamp(meta[0]) if meta else None


def md5(path, chunk=1 << 20):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def sample_frames(path, max_frames=12, with_groups=False):
    """Frames spread across the WHOLE clip, in short bursts.

    Two problems with taking `max_frames` frames `fps/SAMPLE_FPS` apart from
    the head of the file: at 20fps that covers the first six seconds and no
    more, so 54 seconds of every 60-second segment were never examined at all
    - anything that happened later in a clip simply could not be detected.

    Bursts rather than an even spread, because motion is scored by differencing
    consecutive samples: frames five seconds apart would make every drifting
    shadow look like a car. Within a burst the spacing is unchanged, so scores
    stay comparable with everything measured so far; the bursts themselves are
    spread over the clip for coverage. Callers difference only within a burst,
    which is what the group ids are for.

    Reading is sequential with grab(): seeking to each sample with
    CAP_PROP_POS_FRAMES re-decodes from the preceding keyframe every time,
    which cost ~20 seconds a clip. grab() skips the colour conversion for
    frames we are going to throw away.
    """
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return ([], []) if with_groups else []
    fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total <= 0:
        cap.release()
        return ([], []) if with_groups else []

    step = max(1, int(round(fps / SAMPLE_FPS)))
    per_burst = max(2, min(max_frames, BURST_FRAMES))
    bursts = max(1, max_frames // per_burst)

    # Where each burst starts, spread over the clip.
    span = max(1, total - per_burst * step)
    # Divide by bursts-1 so the final burst starts at `span` and the samples
    # actually reach the end of the clip rather than stopping ~17% short.
    starts = [int(round(b * span / float(bursts - 1)))
              for b in range(bursts)] if bursts > 1 else [0]

    # One seek per burst, then walk forward inside it. Seeking to every single
    # sample re-decodes from the preceding keyframe each time; walking the
    # whole file instead is worse on a long clip (measured 6.9s vs 3.4s on a
    # 1200-frame segment). Six seeks plus short walks beats both.
    out, groups = [], []
    for g, st in enumerate(starts):
        if st > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, st)
        pos = st
        for k in range(per_burst):
            target = st + k * step
            if target >= total:
                break
            while pos < target:          # grab() skips the colour conversion
                if not cap.grab():
                    break
                pos += 1
            ok, fr = cap.read()
            if not ok:
                break
            pos += 1
            out.append(fr)
            groups.append(g)
    cap.release()
    return (out, groups) if with_groups else out


def _is_blank(cell):
    """True when this pane carries no picture in this frame.

    Either an unused pane (flat) or the offline placeholder (near-black with
    almost no structure). Both must be excluded from motion: diffing across the
    moment picture becomes placeholder scores the whole pane and reports a
    camera outage as an incident.
    """
    std = float(cell.std())
    if std < DEAD_STD:
        return True
    return float(cell.mean()) < PLACEHOLDER_MEAN and std < PLACEHOLDER_STD


def analyse(path, boxes):
    """Peak motion per pane, the frame where each peaked, and a live mask.

    `boxes` comes from the layout detected for this clip; the mosaic geometry
    changes with how many cameras are online, so a fixed grid would slice one
    camera across several panes and attribute its motion to its neighbours.
    """
    frames, groups = sample_frames(path, SAMPLE_FRAMES, with_groups=True)
    if len(frames) < 2 or not boxes:
        return None, None, None, None
    grays = [cv2.GaussianBlur(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (5, 5), 0)
             for f in frames]

    n = len(boxes)
    motion, peak_at, cover_at = [0] * n, [0] * n, [0] * n

    # Flatness per FRAME, not per clip. The stream composites an absent camera
    # as a flat placeholder tile, so a pane can carry picture early in a clip
    # and be a placeholder for the rest of it - and a max() over the whole clip
    # called that pane live throughout. Diffing the frame where picture becomes
    # placeholder then scored the entire pane as motion: ~60k px on Front, ~84k
    # on Backyard, the same value clip after clip for an hour. Those were not
    # events, they were the camera dropping out, and because the thumbnail is
    # taken at the motion peak they were illustrated with the black tile.
    flat = [[_is_blank(g[y:y + ch, x:x + cw]) for g in grays]
            for (x, y, cw, ch) in boxes]
    # Live means the pane carried picture for most of the clip, not just once.
    live = [sum(1 for f in col if not f) * 2 >= len(grays) for col in flat]

    kernel = np.ones((3, 3), np.uint8)
    for fi, (a, b) in enumerate(zip(grays, grays[1:])):
        # Consecutive samples only within one burst; the jump between bursts is
        # seconds wide and would score as motion on its own.
        if groups[fi] != groups[fi + 1]:
            continue
        d = cv2.absdiff(a, b)
        _, th = cv2.threshold(d, DIFF_THRESH, 255, cv2.THRESH_BINARY)
        th = cv2.morphologyEx(th, cv2.MORPH_OPEN, kernel)
        for idx, (x, y, cw, ch) in enumerate(boxes):
            if not live[idx]:
                continue
            # Only compare two frames that both actually carried picture.
            if flat[idx][fi] or flat[idx][fi + 1]:
                continue
            v = int(cv2.countNonZero(th[y:y + ch, x:x + cw]))
            if v > motion[idx]:
                motion[idx], peak_at[idx] = v, fi + 1
    # Which frame to show. NOT the frame-to-frame motion peak: that is the
    # instant of greatest CHANGE, which for something crossing the view is the
    # moment it leaves - measured on a car pulling out of the garage, the pane
    # differed from its background by 15311px at f2 with the car in shot, and
    # the motion peak landed on f3 at 5093px with the car already gone. The
    # cover looked like an empty driveway.
    #
    # Compare against a background instead and take the frame that differs
    # most: that is the frame where the subject is most present. The score
    # itself is untouched, so thresholds and every number recorded so far stay
    # comparable - only the picture changes.
    base = np.median(np.stack(grays[::3]), axis=0).astype(np.uint8)
    for idx, (x, y, cw, ch) in enumerate(boxes):
        if not live[idx]:
            continue
        best = -1
        for fi, gray in enumerate(grays):
            if flat[idx][fi]:
                continue        # placeholder tile differs hugely and means nothing
            d = cv2.absdiff(base[y:y + ch, x:x + cw], gray[y:y + ch, x:x + cw])
            _, th = cv2.threshold(d, DIFF_THRESH, 255, cv2.THRESH_BINARY)
            th = cv2.morphologyEx(th, cv2.MORPH_OPEN, kernel)
            v = int(cv2.countNonZero(th))
            if v > best:
                best, cover_at[idx] = v, fi
        if best < 0:
            cover_at[idx] = peak_at[idx]

    return motion, frames, live, cover_at


def save_thumb(frame, box, dst):
    x, y, cw, ch = box
    crop = frame[y:y + ch, x:x + cw]
    scale = THUMB_W / float(cw)
    crop = cv2.resize(crop, (THUMB_W, int(ch * scale)))
    cv2.imwrite(dst, crop, [cv2.IMWRITE_JPEG_QUALITY, 82])


def group_incidents(events):
    """Collapse consecutive clips on one camera into a single incident."""
    by_cam = defaultdict(list)
    for e in events:
        if e["ts"]:
            by_cam[e["camera"]].append(e)

    incidents = []
    for cam, evs in by_cam.items():
        evs.sort(key=lambda x: x["ts"])
        cur = None
        for e in evs:
            if cur and (e["ts"] - cur["end"]).total_seconds() <= INCIDENT_GAP_S:
                cur["end"] = e["ts"]
                cur["clips"].append(e)
                if e["score"] > cur["peak"]:
                    cur["peak"] = e["score"]
                    cur["thumb"] = e["thumb"]
            else:
                if cur:
                    incidents.append(cur)
                cur = {"camera": cam, "start": e["ts"], "end": e["ts"],
                       "clips": [e], "peak": e["score"], "thumb": e["thumb"]}
        if cur:
            incidents.append(cur)

    for inc in incidents:
        span = (inc["end"] - inc["start"]).total_seconds()
        # Each clip covers ~20s, so a single-clip incident is not zero-length.
        inc["duration"] = int(span + 20)
    incidents.sort(key=lambda i: i["start"])
    return incidents


def card_html(inc, prefix=""):
    """One incident card. `prefix` shifts relative paths for the hour pages,
    which live one level deeper than summary.html."""
    rng = inc["start"].strftime("%H:%M:%S")
    if inc["end"] != inc["start"]:
        rng += " &ndash; " + inc["end"].strftime("%H:%M:%S")
    return ('<a class=card href="%s../activity/%s">'
            '<img loading=lazy src="%s%s" alt="">'
            '<div class=meta><div class=cam>%s</div>'
            '<div class=time>%s</div>'
            '<div class=sub>%s &middot; %d clip%s</div></div></a>'
            % (prefix, html.escape(inc["clips"][0]["file"]),
               prefix, html.escape(inc["thumb"]),
               html.escape(inc["camera"]), rng,
               human_duration(inc["duration"]), len(inc["clips"]),
               "" if len(inc["clips"]) == 1 else "s"))


def hour_cameras(seen_by_hour, hh):
    """(online, offline) for one hour, from the layout the stream used.

    The mosaic only contains cameras that were streaming when it was
    composited, so its pane labels are the record of who was up that hour.
    """
    cams = (seen_by_hour or {}).get(hh)
    if cams is None:
        return None, None
    online = [c for c in CAMS if c in cams]
    return online, [c for c in CAMS if c not in cams]


def cam_status_html(online, offline, cls="camline"):
    if online is None:
        return ""
    bits = ['<span class=%s>online: <b>%s</b>' % (cls, ", ".join(online) or "none")]
    if offline:
        bits.append(' &middot; <span class=off>offline: %s</span>'
                    % ", ".join(offline))
    return html_join(bits) + "</span>"


def html_join(bits):
    return "".join(bits)


def write_hour_pages(day, summ, by_hour, hours, seen_by_hour=None):
    """A standalone page per hour, saved alongside the day summary.

    The day page is long once a busy day fills up; these answer 'what happened
    in the last hour' on its own, and each one persists as part of the day.
    """
    hdir = os.path.join(summ, "hourly")
    os.makedirs(hdir, exist_ok=True)
    active = [h for h in hours if by_hour.get(h)]

    for i, hh in enumerate(active):
        group = by_hour[hh]
        per_cam = defaultdict(int)
        for inc in group:
            per_cam[inc["camera"]] += 1
        longest = max(group, key=lambda x: x["duration"])
        busiest = max(per_cam.items(), key=lambda kv: kv[1])
        head = "%d %s between %s and %s." % (
            len(group), "incident" if len(group) == 1 else "incidents",
            slot_label(hh), slot_end_label(hh))
        sub = ("Mostly <b>%s</b> (%d). Longest ran <b>%s</b> at %s." % (
            html.escape(busiest[0]), busiest[1],
            human_duration(longest["duration"]),
            longest["start"].strftime("%H:%M:%S")))

        nav = []
        if i > 0:
            nav.append('<a href="%s.html">&larr; %s</a>'
                       % (active[i - 1], slot_label(active[i - 1])))
        nav.append('<a href="../summary.html">full day</a>')
        if i < len(active) - 1:
            nav.append('<a href="%s.html">%s &rarr;</a>'
                       % (active[i + 1], slot_label(active[i + 1])))

        cards = "".join(card_html(inc, prefix="../") for inc in group)
        chips = "".join('<span class=chip><b>%s</b> %d</span>'
                        % (html.escape(c), n)
                        for c, n in sorted(per_cam.items()))
        on, off = hour_cameras(seen_by_hour, hh)
        if on is None:
            cams_block = ""
        else:
            cams_block = ('<h2>Cameras online</h2><div>'
                          + "".join('<span class=chip on><b>%s</b></span>'
                                    % html.escape(c) for c in on)
                          + "".join('<span class=chip offc><b>%s</b> offline'
                                    '</span>' % html.escape(c) for c in off)
                          + '</div>')
        page = HOUR_PAGE.format(
            css="../style.css", day=day, hh=slot_label(hh),
            headline=head, sub=sub,
            n=len(group), cams=len(per_cam),
            clips=sum(len(x["clips"]) for x in group),
            nav=" &middot; ".join(nav), chips=chips, cards=cards,
            cams_block=cams_block)
        with open(os.path.join(hdir, hh + ".html"), "w",
                  encoding="utf-8") as f:
            f.write(page)

    rows = []
    for hh in hours:
        group = by_hour.get(hh)
        on, off = hour_cameras(seen_by_hour, hh)
        if on is None:
            cov = "no footage"
        else:
            cov = "%d/%d online: %s" % (len(on), len(CAMS), ", ".join(on))
            if off:
                cov += "  |  offline: " + ", ".join(off)
        if group:
            rows.append('<a class=hrow href="%s.html"><b>%s</b>'
                        '<span>%d incident%s</span><em>%s</em></a>'
                        % (hh, slot_label(hh), len(group),
                           "" if len(group) == 1 else "s", html.escape(cov)))
        else:
            rows.append('<div class="hrow quiet"><b>%s</b>'
                        '<span>%s</span><em>%s</em></div>'
                        % (slot_label(hh),
                           "quiet" if on is not None else "&mdash;",
                           html.escape(cov)))
    with open(os.path.join(hdir, "index.html"), "w", encoding="utf-8") as f:
        f.write(HOUR_INDEX.format(css="../style.css", day=day,
                                  rows="".join(rows), active=len(active)))
    return active


def human_duration(sec):
    if sec < 60:
        return "%ds" % sec
    m, s = divmod(int(sec), 60)
    if m < 60:
        return "%dm %02ds" % (m, s) if s else "%dm" % m
    h, m = divmod(m, 60)
    return "%dh %02dm" % (h, m)


def drive_link(day):
    """Link to this day's Google Drive folder, or '' if it is not up there.

    The id comes from state/drive_folders.json, written by the upload step.
    Opening that URL still requires access to the account, so recording the id
    shares nothing and makes nothing public.
    """
    try:
        ids = json.load(open(os.path.join(BASE, "state", "drive_folders.json")))
    except Exception:
        return ""
    fid = ids.get(day)
    if not fid:
        return ""
    return ('&middot; <a href="https://drive.google.com/drive/folders/%s"'
            ' target="_blank" rel="noopener">Google Drive copy &#8599;</a>'
            % html.escape(str(fid)))


def carry_events(summ, covered):
    """Events from the last complete build, for hours this run did not analyse.

    events_base.csv is a snapshot of a build that covered the whole day. Rows
    are used only for hours the current cache has nothing for, so a freshly
    analysed hour always wins over the snapshot and nothing is double-counted.
    """
    path = os.path.join(summ, "events_base.csv")
    if not os.path.exists(path):
        return []
    out = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    ts = datetime.datetime.fromisoformat(row["time"])
                except Exception:
                    continue
                hh = slot_key(ts)
                if hh in covered:
                    continue
                fn = row["file"]
                out.append({
                    "ts": ts, "hour": hh, "camera": row["camera"],
                    "score": int(row["motion_px"]), "clip": row["clip"],
                    "file": fn,
                    "thumb": "thumbs/" + fn.rsplit(".", 1)[0] + ".jpg",
                })
    except Exception as e:
        print("  carry_events: %s" % e, flush=True)
        return []
    if out:
        print("  carried %d events from %d earlier hours"
              % (len(out), len({e["hour"] for e in out})),
              flush=True)
    return out


def publish(cc, day, out, summ, hours_dir, clips, indexed_hours):
    """Aggregate the cache and write the pages.

    Split out of build_day so it can run at every checkpoint, not only
    when the whole day has finished decoding. A full rebuild is hours of
    work, and the page used to be written once at the very end - so for
    the entire run the site still showed the previous build and every
    hour recorded since was simply absent.

    It only reads the cache, so it costs seconds.
    """
    # ---- rebuild the whole day's model from cache (cheap, no decoding) ----
    events, dupes = [], 0
    hourly = defaultdict(lambda: defaultdict(int))
    cam_seen = set()
    for vid, rec in cc.items():
        if rec.get("dup"):
            dupes += 1
            continue
        if rec.get("bad") or not rec.get("ts"):
            continue
        ts = datetime.datetime.fromtimestamp(rec.get("ets") or rec["ts"])
        hh = slot_key(ts)
        rec_cams = rec.get("cams") or []
        for ci, score in enumerate(rec["m"]):
            if not rec["l"][ci] or ci >= len(rec_cams):
                continue
            cam = rec_cams[ci]
            cam_seen.add(cam)
            if score > hourly[hh][cam]:
                hourly[hh][cam] = score
            if score < MOTION_PX:
                continue
            # Place the event where its motion actually peaked, rather than
            # at the head of a clip that may span a quarter of an hour.
            ets = _event_time(rec, ci, ts)
            hh = slot_key(ets)
            stamp = rec.get("st") or ts.strftime("%H%M%S")
            events.append({"ts": ets, "hour": hh, "camera": cam,
                           "score": score, "clip": vid,
                           "file": "%s_%s.mp4" % (stamp, slug(cam)),
                           "thumb": "thumbs/%s_%s.jpg" % (stamp, slug(cam))})

    fetched_hours = defaultdict(int)
    for rec in cc.values():
        if rec.get("ts"):
            fetched_hours[slot_key(datetime.datetime.fromtimestamp(
                rec.get("ets") or rec["ts"]))] += 1
    hour_counts = {h: {"indexed": indexed_hours.get(h, 0),
                       "fetched": fetched_hours.get(h, 0)}
                   for h in set(indexed_hours) | set(fetched_hours)}

    # Cameras the mosaic actually carried today, hour by hour. Anything in
    # CAMS that never appeared was offline for the whole day.
    # Which cameras were genuinely live each hour. The stream now composites
    # every camera's pane whether or not it answered, feeding a dark
    # placeholder when it did not - so a camera's presence in the layout no
    # longer proves it was up. A placeholder pane is uniformly flat and fails
    # the DEAD_STD test, which is what `l` records, so liveness is the signal.
    live_by_hour = defaultdict(set)
    for rec in cc.values():
        if rec.get("dup") or rec.get("bad") or not rec.get("ts"):
            continue
        hh = slot_key(datetime.datetime.fromtimestamp(
            rec.get("ets") or rec["ts"]))
        rcams = rec.get("cams") or []
        for ci, alive in enumerate(rec.get("l") or []):
            if alive and ci < len(rcams):
                live_by_hour[hh].add(rcams[ci])
    seen_by_hour = {h: [c for c in CAMS if c in v]
                    for h, v in live_by_hour.items() if v}
    present = {c for cams in seen_by_hour.values() for c in cams}
    missing = [c for c in CAMS if c not in present]
    partial = [c for c in CAMS
               if c in present
               and any(c not in cams for cams in seen_by_hour.values())]

    # Hours the cache does not cover - because they fall outside the analysis
    # window, or were never re-decoded after a cache reset - would otherwise
    # vanish from the page. Their events were already computed by an earlier
    # complete build, and their thumbnails and clips are still on disk, so
    # carry those rows through rather than blanking the hours.
    carried = carry_events(summ, {e["hour"] for e in events})
    for e in carried:
        events.append(e)
        hh, cam = e["hour"], e["camera"]
        if e["score"] > hourly[hh][cam]:
            hourly[hh][cam] = e["score"]
        cam_seen.add(cam)

    incidents = group_incidents(events)
    write_outputs(day, out, summ, events, incidents, hourly, hours_dir,
                  sorted(cam_seen), len(clips), len(cc) - dupes, dupes,
                  hour_counts=hour_counts, missing=missing, partial=partial,
                  seen_by_hour=seen_by_hour)
    return events, incidents, dupes


def build_day(day):
    cdir = os.path.join(BASE, "clips", day)
    if not os.path.isdir(cdir):
        print("no clips for", day)
        return
    out = os.path.join(BASE, "daily", day)
    act = os.path.join(out, "activity")
    summ = os.path.join(out, "summary")
    thumbs = os.path.join(summ, "thumbs")
    for d in (act, summ, thumbs):
        os.makedirs(d, exist_ok=True)

    hours_dir = os.path.join(summ, "hours")
    os.makedirs(hours_dir, exist_ok=True)

    # A missing index is normal on a first run (a fresh runner, or a day
    # before anything was ever indexed) - it only enriches the timeline with
    # "listed but not fetched yet", so carry on without it rather than dying.
    try:
        idx_rows = json.load(open(os.path.join(BASE, "state",
                                              "vods_index.json")))
    except Exception:
        idx_rows = []
    idx = {r[1]: r for r in idx_rows}
    # What Twitch lists for this day, per hour. Compared against what is
    # actually on disk this separates "nothing happened" from "not fetched
    # yet", which matters on today's page since it is always mid-download.
    indexed_hours = defaultdict(int)
    for _ts, _vid, _dur, _url in idx_rows:
        _d = datetime.datetime.fromtimestamp(_ts)
        if _d.strftime("%Y-%m-%d") == day:
            indexed_hours[slot_key(_d)] += 1
    clips = sorted(f for f in os.listdir(cdir) if f.endswith(".mp4"))

    # Decoding video is the expensive stage, so per-clip results are cached.
    # An hourly run then only touches clips that arrived since the last one,
    # which keeps a re-run to minutes instead of the better part of an hour.
    cache_path = os.path.join(out, "analysis.json")
    # v4 ignores frames where a pane is the offline placeholder. v3 diffed
    # across the moment a camera dropped and scored the whole pane as motion,
    # so an outage became a stream of incidents illustrated with black tiles.
    # v3 stores the detected camera name per pane. v2 attributed motion by
    # fixed grid position, which mislabels every day where fewer than six
    # cameras were streaming, so those caches are discarded not upgraded.
    cache = {"v": 10, "clips": {}}
    if os.path.exists(cache_path):
        try:
            old = json.load(open(cache_path))
            if old.get("v") == 10:
                cache = old
        except Exception:
            pass
    cc = cache["clips"]

    fresh = [f for f in clips if f[:-4] not in cc]

    # The window is an absolute wall-clock cutoff, deliberately NOT "only if
    # this is today". Gating it on today meant that at midnight yesterday
    # stopped qualifying and the next tick started re-decoding the entire day
    # from scratch - 1011 clips, hours of work, collection blocked throughout.
    # An absolute cutoff does the right thing in both cases: it still picks up
    # the tail of a day that just ended, and it excludes everything older,
    # which carry_events keeps on the page anyway.
    # Set RECENT_HOURS=0 to force a genuine full rebuild of a day.
    if RECENT_HOURS > 0:
        cutoff = datetime.datetime.now() - datetime.timedelta(hours=RECENT_HOURS)
        windowed = [f for f in fresh
                    if (clip_time(f[:-4], idx) or datetime.datetime.min) >= cutoff]
        if len(windowed) != len(fresh):
            print("  window: %d of %d new clips are within the last %dh"
                  % (len(windowed), len(fresh), RECENT_HOURS), flush=True)
        fresh = windowed
    # Newest first. A full rebuild takes hours, and the hours people actually
    # want to look at are the ones that just happened - processing in name
    # order meant the current evening was last to appear, behind a whole day
    # of old footage. Combined with publishing at each checkpoint, recent
    # hours now show up within minutes and the rest backfills behind them.
    fresh.sort(key=lambda f: (clip_time(f[:-4], idx) or datetime.datetime.min),
               reverse=True)
    print("[%s] %d clips (%d new, %d cached)"
          % (day, len(clips), len(fresh), len(clips) - len(fresh)), flush=True)

    seen_md5 = {v["md5"] for v in cc.values() if not v.get("dup")}
    # OCR is expensive, so the layout is read once per hour and reused. A
    # camera dropping out mid-hour is picked up at the next hour boundary.
    layout_cache = cache.setdefault("layouts", {})
    # Per-run, deliberately not persisted: a slot whose labels the OCR could
    # not read today may read cleanly on a later pass over the same day.
    layout_miss = {}
    for n, fn in enumerate(fresh, 1):
        vid = fn[:-4]
        p = os.path.join(cdir, fn)
        digest = md5(p)
        if digest in seen_md5:
            cc[vid] = {"md5": digest, "dup": True}
            continue
        seen_md5.add(digest)

        ts = clip_time(vid, idx)
        boxes, cams_here = None, []
        hh_key = slot_key(ts) if ts else "??"
        if hh_key not in layout_cache and layout_miss.get(hh_key, 0) < 2:
            # Labels sit over live video, so a single frame can defeat OCR
            # (white text on bright foliage). Try a few before giving up.
            # Two frames, not six: each attempt is a full candidate sweep,
            # so retrying a frame that cannot be read is the single most
            # expensive thing this loop can do.
            probe = sample_frames(p, LAYOUT_PROBE_FRAMES)
            ln = lnames = None
            for fr in probe:
                ln, lnames = detect_layout(fr)
                if ln:
                    break
            if ln:
                layout_cache[hh_key] = {"n": ln, "cams": lnames}
            else:
                # A failure is worth retrying once or twice, because a later
                # clip in the slot may read cleanly - but not forever: a slot
                # the OCR simply cannot read was costing a full failed sweep
                # on every single clip in it. After a couple of tries, settle
                # for the borrowed layout and stop paying for detection.
                layout_miss[hh_key] = layout_miss.get(hh_key, 0) + 1

        lay = layout_cache.get(hh_key)
        if lay and lay.get("n"):
            boxes = LAYOUTS.get(lay["n"])
            cams_here = lay["cams"] or []
        else:
            # Detection failed, or was skipped because this slot has already
            # missed twice. Borrow the layout from the nearest slot that did
            # read - the camera count rarely changes from one hour to the next.
            #
            # This branch used to be reachable only from inside the detection
            # block, so once the miss cap silenced detection nothing assigned
            # `boxes` at all and every remaining clip in the slot was marked
            # "bad": 22:00 showed as empty on the page while nine clips sat on
            # disk. Borrowing has to happen whenever the cache has no entry,
            # not only when detection was actually attempted.
            known = [k for k in layout_cache if layout_cache[k].get("n")]
            if known:
                nearest = min(known, key=lambda k: abs(int(k) - int(hh_key))
                              if hh_key.isdigit() else 0)
                lay = layout_cache[nearest]
                boxes = LAYOUTS.get(lay["n"])
                cams_here = lay["cams"] or []
        if not boxes:
            cc[vid] = {"md5": digest, "dup": False, "bad": True}
            continue

        motion, frames, live, cover_at = analyse(p, boxes)
        if motion is None:
            cc[vid] = {"md5": digest, "dup": False, "bad": True}
            continue

        # Anchor on a sample, not every clip. The pull-to-film offset drifts
        # smoothly, so interpolating between anchors places the clips in
        # between just as well - and at 2.6-6s per tesseract call, reading
        # every clip put the job four hours behind, during which nothing new
        # was collected at all.
        do_ocr = OCR_CLOCK and (n % OCR_EVERY == 0 or n >= len(fresh) - 1)
        cts = cte = None
        eff = ts
        # Read the burnt-in clock while the sampled frames are still in hand.
        # Both ends, because a clip is not a minute of real time: the mosaic
        # segments are themselves time-compressed, so 60 seconds of broadcast
        # has been measured carrying anywhere from 4 to 19 minutes of camera
        # time. One stamp for the whole clip would put an event up to a quarter
        # of an hour from where it happened.
        if do_ocr:
            cts = _clock_near(frames, 0)
            cte = _clock_near(frames, len(frames) - 1)
            if cts and cte and cte < cts:
                cte = None      # a discontinuity; do not interpolate across it
            eff = cts or ts

        hh = slot_key(eff) if eff else "??"
        hf = os.path.join(hours_dir, hh + ".jpg")
        if not os.path.exists(hf):
            cv2.imwrite(hf, cv2.resize(frames[len(frames) // 2], (320, 120)),
                        [cv2.IMWRITE_JPEG_QUALITY, 80])

        stamp = eff.strftime("%H%M%S") if eff else None
        for ci, score in enumerate(motion):
            if not live[ci] or score < MOTION_PX or eff is None:
                continue
            cam = cams_here[ci]
            dst = os.path.join(act, "%s_%s.mp4" % (stamp, slug(cam)))
            if not os.path.exists(dst):
                shutil.copy2(p, dst)
            save_thumb(frames[cover_at[ci]], boxes[ci],
                       os.path.join(summ, "thumbs/%s_%s.jpg" % (stamp, slug(cam))))

        cc[vid] = {"md5": digest, "dup": False,
                   "m": [int(x) for x in motion],
                   "l": [bool(x) for x in live],
                   "cams": cams_here,
                   # `st` is the stamp the thumbnail and activity clip were
                   # actually written under, so the links keep resolving even
                   # when `ets` is later refined by interpolation.
                   "st": stamp,
                   "ts": int(ts.timestamp()) if ts else None,
                   "cts": int(cts.timestamp()) if cts else None,
                   "cte": int(cte.timestamp()) if cte else None,
                   "nf": len(frames),
                   "p": [int(x) for x in cover_at]}

        if n % 100 == 0:
            # Checkpoint. A full rebuild is hours of work and the cache used to
            # be written only at the very end, so every interruption - a crash,
            # a reboot, someone stopping the job - threw all of it away and the
            # next run started from zero. Written to a temp file and renamed so
            # a kill mid-write cannot leave a truncated cache behind.
            tmp = cache_path + ".tmp"
            json.dump(cache, open(tmp, "w"))
            os.replace(tmp, cache_path)
            # The cache is always saved; the PAGE is only replaced from a
            # partial one when asked for. A partial cache is missing most of
            # the day, so publishing from it would blank hours that are
            # currently on the page and only restore them as the backfill
            # catches up - worse than showing the last complete build.
            note = "cache saved"
            if PUBLISH_PARTIAL:
                try:
                    apply_content_times(cc)
                    publish(cc, day, out, summ, hours_dir, clips,
                            indexed_hours)
                    note = "published (partial)"
                except Exception as e:               # never lose the run
                    note = "publish failed: %s" % e
            print("  analysed %d/%d new (checkpointed, %s)"
                  % (n, len(fresh), note), flush=True)

    read_ok = apply_content_times(cc)
    usable = sum(1 for r in cc.values()
                 if not r.get("dup") and not r.get("bad") and r.get("ts"))
    print("  burnt-in clock read on %d/%d clips; the rest interpolated"
          % (read_ok, usable), flush=True)
    json.dump(cache, open(cache_path, "w"))

    events, incidents, dupes = publish(cc, day, out, summ, hours_dir,
                                       clips, indexed_hours)
    print("[%s] done: %d unique (%d dupes), %d clips in %d incidents"
          % (day, len(cc) - dupes, dupes, len(events), len(incidents)),
          flush=True)


def write_outputs(day, out, summ, events, incidents, hourly, hours_dir,
                  cams, total, uniq, dupes, hour_counts=None,
                  missing=None, partial=None, seen_by_hour=None):
    with open(os.path.join(summ, "events.csv"), "w", newline="",
              encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["time", "camera", "motion_px", "clip", "file"])
        for e in sorted(events, key=lambda x: (x["ts"] or datetime.datetime.min)):
            wr.writerow([e["ts"].isoformat() if e["ts"] else "", e["camera"],
                         e["score"], e["clip"], e["file"]])

    hours = all_slots()
    # Hour frames are cached to disk as they are first seen, so the contact
    # sheet can be rebuilt on every hourly pass without re-reading any video.
    if isinstance(hours_dir, str) and os.path.isdir(hours_dir):
        tiles = []
        for hh in hours:
            hf = os.path.join(hours_dir, hh + ".jpg")
            fr = cv2.imread(hf) if os.path.exists(hf) else None
            t = (cv2.resize(fr, (320, 120)) if fr is not None
                 else np.zeros((120, 320, 3), np.uint8))
            cv2.putText(t, slot_label(hh), (6, 16), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (0, 255, 255), 1)
            tiles.append(t)
        # 48 half-hour tiles now, so six across keeps the sheet square.
        per_row = 6
        while len(tiles) % per_row:
            tiles.append(np.zeros((120, 320, 3), np.uint8))
        rows = [np.hstack(tiles[i:i + per_row])
                for i in range(0, len(tiles), per_row)]
        cv2.imwrite(os.path.join(summ, "contact_sheet.jpg"), np.vstack(rows),
                    [cv2.IMWRITE_JPEG_QUALITY, 85])

    per_cam = defaultdict(int)
    for inc in incidents:
        per_cam[inc["camera"]] += 1
    covered = sorted(hourly.keys())
    busiest = (max(hourly.items(), key=lambda kv: sum(kv[1].values()))[0]
               if hourly else None)

    manifest = {
        "day": day, "clips_total": total, "clips_unique": uniq,
        "duplicates": dupes, "activity_clips": len(events),
        "incidents": len(incidents), "cameras": cams,
        "incidents_per_camera": dict(per_cam), "busiest_hour": busiest,
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    json.dump(manifest, open(os.path.join(out, "manifest.json"), "w"), indent=2)

    # ---------- headline ----------
    if not incidents:
        headline = "Nothing moved all day."
        sub = "%d clips checked across %d cameras." % (uniq, len(cams))
    else:
        longest = max(incidents, key=lambda i: i["duration"])
        top_cam = max(per_cam.items(), key=lambda kv: kv[1])
        headline = "%d %s across %d %s." % (
            len(incidents), "incident" if len(incidents) == 1 else "incidents",
            len(per_cam), "camera" if len(per_cam) == 1 else "cameras")
        sub = ("Busiest was <b>%s</b> with %d. Longest ran <b>%s</b> on "
               "<b>%s</b> at %s." % (
                   html.escape(top_cam[0]), top_cam[1],
                   human_duration(longest["duration"]),
                   html.escape(longest["camera"]),
                   longest["start"].strftime("%-I:%M %p")
                   if os.name != "nt" else longest["start"].strftime("%I:%M %p").lstrip("0")))

    # ---------- hour timeline: bars link to their hour's section ----------
    counts = defaultdict(int)
    by_hour = defaultdict(list)
    for inc in incidents:
        hh = slot_key(inc["start"])
        counts[hh] += 1
        by_hour[hh].append(inc)
    peak = max(counts.values()) if counts else 1

    bars = []
    for hh in hours:
        c = counts.get(hh, 0)
        seen_hour = hh in hourly
        hc = (hour_counts or {}).get(hh, {})
        pending = max(0, hc.get("indexed", 0) - hc.get("fetched", 0))
        pct = int(18 + 82 * (c / float(peak))) if c else 0
        if c:
            cls = "b"
            title = "%s - %d incident%s" % (slot_label(hh), c,
                                            "" if c == 1 else "s")
        elif seen_hour:
            cls = "q"
            title = "%s - quiet" % slot_label(hh)
        elif pending:
            # Twitch lists clips for this hour that the archive has not pulled
            cls = "p"
            title = "%s - %d clip%s not fetched yet" % (
                slot_label(hh), pending, "" if pending == 1 else "s")
        else:
            cls = "n"
            title = "%s - no footage" % slot_label(hh)
        inner = ('<div class="bar %s" style="height:%d%%"></div>'
                 '<span class=c>%s</span><span class=t>%s</span>'
                 % (cls, pct, ("%d" % c) if c else "",
                    hh[:2] if hh.endswith("00") else ""))
        # Only hours with incidents are navigable; the rest stay inert.
        if c:
            bars.append('<a class=h href="#h%s" title="%s">%s</a>'
                        % (hh, title, inner))
        else:
            bars.append('<div class=h title="%s">%s</div>' % (title, inner))

    # ---------- incident cards, grouped under their hour ----------
    def card(inc):
        return card_html(inc)

    sections = []
    for hh in hours:
        group = by_hour.get(hh)
        if not group:
            continue
        online, offline = hour_cameras(seen_by_hour, hh)
        status = (cam_status_html(online, offline)
                  if online is not None
                  else "<span class=camline>%s</span>"
                       % html.escape(", ".join(
                           sorted({i["camera"] for i in group}))))
        sections.append(
            '<section class=hour id="h%s">%s<h3>%s'
            '<span>%d incident%s</span>%s'
            '<a class=top href="hourly/%s.html">this slot only</a>'
            '<a class=top href="#top">top</a></h3>'
            '<div class=grid>%s</div></section>'
            # Keep the old #hHH anchor alive on the first slot of each hour
            # so links already shared by email and chat still land.
            % (hh,
               '<span id="h%s"></span>' % hh[:2] if hh.endswith("00") else "",
               slot_label(hh), len(group),
               "" if len(group) == 1 else "s", status, hh,
               "".join(card(i) for i in group)))
    if not sections:
        sections.append('<p class=none>No movement passed the detection '
                        'threshold on any camera today.</p>')
    cards = sections

    cam_chips = "".join(
        '<span class=chip><b>%s</b> %d</span>'
        % (html.escape(c), per_cam.get(c, 0)) for c in cams)

    coverage = ("%s &ndash; %s" % (slot_label(covered[0]),
                                   slot_end_label(covered[-1]))
                if covered else "no footage")

    active_hours = write_hour_pages(day, summ, by_hour, hours,
                                    seen_by_hour=seen_by_hour)
    manifest["hours_with_activity"] = active_hours
    json.dump(manifest, open(os.path.join(out, "manifest.json"), "w"), indent=2)

    missing = missing or []
    partial = partial or []

    # Coverage headline: how many cameras the most recent hour actually carried.
    latest_cams = None
    if seen_by_hour:
        latest_cams = seen_by_hour[max(seen_by_hour)]
    cam_stat = ("%d / %d" % (len(latest_cams), len(CAMS))
                if latest_cams is not None else "?")
    cam_stat_label = ("cameras online" if latest_cams is not None
                      else "cameras")

    # The live player only makes sense on today's page; older days are history.
    # Twitch requires `parent` to match the hostname serving the page, and this
    # is reached by LAN IP today and possibly a tunnel domain later, so the src
    # is set from location.hostname rather than hardcoded.
    if day == datetime.date.today().strftime("%Y-%m-%d"):
        live = LIVE_BLOCK.replace("__CH__", CHANNEL)
    else:
        live = ""
    if missing or partial:
        bits = []
        if missing:
            bits.append("<b>%s</b> %s offline all day"
                        % (html.escape(", ".join(missing)),
                           "was" if len(missing) == 1 else "were"))
        if partial:
            gone = []
            for c in partial:
                hrs = sorted(h for h, cams in (seen_by_hour or {}).items()
                             if c not in cams)
                gone.append("%s (missing %s)"
                            % (html.escape(c),
                               ", ".join(h + ":00" for h in hrs[:6])
                               + ("&hellip;" if len(hrs) > 6 else "")))
            bits.append("Intermittent: " + "; ".join(gone))
        alert = ('<div class=alert><b>Camera coverage gap</b>'
                 '<div>%s</div></div>' % " &middot; ".join(bits))
    else:
        alert = ""

    # One stylesheet shared by the day page and every hour page.
    with open(os.path.join(summ, "style.css"), "w", encoding="utf-8") as f:
        f.write(STYLE_CSS)

    page = PAGE.format(
        css="style.css",
        day=day, headline=headline, sub=sub,
        incidents=len(incidents), uniq=uniq, dupes=dupes,
        clips=len(events), coverage=coverage,
        bars="".join(bars), cards="".join(cards), chips=cam_chips,
        alert=alert, live=live,
        cam_stat=cam_stat, cam_stat_label=cam_stat_label,
        hourly=('<a class=hourlink href="hourly/index.html">'
                'Browse hour by hour &rarr;</a>' if active_hours else ""),
        drive=drive_link(day),
        generated=manifest["generated"].replace("T", " "))
    with open(os.path.join(summ, "summary.html"), "w", encoding="utf-8") as f:
        f.write(page)


STYLE_CSS = """:root{--bg:#fbfaf8;--fg:#23211e;--mut:#6f6a63;--line:#e5e1db;--card:#fff;
--accent:#b4531f;--quiet:#cfc9c0;--none:#eeeae4;--pend:#c9a227;--alertbg:#fdf4e3;--alertbd:#d9963c}
@media(prefers-color-scheme:dark){:root{--bg:#161513;--fg:#ece9e4;
--mut:#9a948b;--line:#2e2b27;--card:#1e1c1a;--accent:#e0834a;
--quiet:#403c36;--none:#26231f;--pend:#8a7420;--alertbg:#2a2216;--alertbd:#8a6420}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:32px 20px 64px}
.date{color:var(--mut);font-size:13px;letter-spacing:.08em;
text-transform:uppercase;margin-bottom:6px}
h1{font-size:27px;line-height:1.25;margin:0 0 8px;font-weight:640;
letter-spacing:-.01em}
.sub{color:var(--mut);font-size:15px;margin:0 0 26px}
.stats{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:34px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:9px;
padding:10px 15px}
.stat b{display:block;font-size:21px;font-weight:640;letter-spacing:-.01em}
.stat span{color:var(--mut);font-size:12px}
h2{font-size:13px;letter-spacing:.08em;text-transform:uppercase;
color:var(--mut);font-weight:600;margin:38px 0 14px;
padding-bottom:8px;border-bottom:1px solid var(--line)}
.tlwrap{position:sticky;top:0;z-index:5;background:var(--bg);
padding:10px 0 12px;margin-bottom:4px}
.tl{display:flex;align-items:flex-end;gap:3px;height:116px;
background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:12px 10px 6px}
.h{flex:1;display:flex;flex-direction:column;align-items:center;
justify-content:flex-end;height:100%;position:relative;
text-decoration:none;color:inherit;border-radius:4px}
a.h{cursor:pointer}
a.h:hover .bar{filter:brightness(1.12)}
a.h:hover{background:rgba(127,127,127,.10)}
a.h:hover .t{color:var(--fg)}
section.hour{scroll-margin-top:168px}
section.hour h3{display:flex;align-items:baseline;gap:11px;
font-size:16px;font-weight:640;letter-spacing:0;text-transform:none;
color:var(--fg);margin:30px 0 13px;padding-bottom:9px;
border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}
section.hour h3 span{font-size:13px;font-weight:400;color:var(--mut)}
a.top{margin-left:auto;font-size:12px;font-weight:400;color:var(--mut);
text-decoration:none}
a.top:hover{color:var(--accent)}
html{scroll-behavior:smooth}
.bar{width:100%;border-radius:3px 3px 0 0;min-height:3px}
.bar.b{background:var(--accent)}
.bar.q{background:var(--quiet);height:3px!important}
.bar.n{background:var(--none);height:3px!important}
.bar.p{background:repeating-linear-gradient(45deg,var(--pend),var(--pend) 2px,transparent 2px,transparent 5px);height:30%!important;border-radius:3px 3px 0 0}
.c{font-size:11px;color:var(--fg);font-weight:600;margin-top:3px;height:13px}
.t{font-size:10px;color:var(--mut)}
.grid{display:grid;gap:14px;
grid-template-columns:repeat(auto-fill,minmax(240px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
overflow:hidden;text-decoration:none;color:inherit;display:block;
transition:border-color .12s,transform .12s}
.card:hover{border-color:var(--accent);transform:translateY(-2px)}
.card img{width:100%;display:block;aspect-ratio:16/9;object-fit:cover;
background:var(--none)}
.meta{padding:10px 12px 12px}
.cam{font-weight:640;font-size:14px}
.time{font-variant-numeric:tabular-nums;font-size:13px;margin-top:1px}
.sub2,.sub{color:var(--mut)}
.meta .sub{font-size:12px;margin:2px 0 0}
.chip{display:inline-block;background:var(--card);border:1px solid var(--line);
border-radius:20px;padding:5px 13px;margin:0 7px 7px 0;font-size:13px}
.chip b{font-weight:600}
.none{color:var(--mut)}
img.sheet{width:100%;border:1px solid var(--line);border-radius:10px}
footer{margin-top:42px;color:var(--mut);font-size:12px;
border-top:1px solid var(--line);padding-top:14px}
.hourlink{display:inline-block;margin:2px 0 6px;font-size:14px;
color:var(--accent);text-decoration:none;font-weight:600}
.hourlink:hover{text-decoration:underline}
.nav{margin:0 0 22px;font-size:14px}
.nav a{color:var(--accent);text-decoration:none}
.nav a:hover{text-decoration:underline}
.hrow{display:flex;align-items:baseline;gap:14px;padding:11px 14px;
border:1px solid var(--line);border-radius:9px;background:var(--card);
margin-bottom:7px;text-decoration:none;color:inherit}
a.hrow:hover{border-color:var(--accent)}
.hrow b{font-variant-numeric:tabular-nums;min-width:60px;font-weight:640}
.hrow span{color:var(--mut);font-size:13px;min-width:108px}
.hrow em{color:var(--mut);font-size:13px;font-style:normal}
.hrow.quiet{opacity:.55}
.camline{font-size:12px;font-weight:400;color:var(--mut)}
.camline b{font-weight:600;color:var(--fg)}
.off{color:var(--alertbd);font-weight:600}
.chip.on b{color:var(--fg)}
.chip.offc{opacity:.65;border-style:dashed;color:var(--alertbd)}
.live{position:relative;aspect-ratio:8/3;max-width:760px;background:#000;border:1px solid var(--line);border-radius:10px;overflow:hidden}
.live iframe,.live video,.live img{position:absolute;inset:0;width:100%;height:100%;border:0;object-fit:fill;background:#000;display:block}
.live .msg{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--mut);font-size:13px;text-align:center;padding:20px}
.lvst{display:inline-flex;align-items:center;gap:7px;font-size:13px;color:var(--mut);margin:0 0 9px}
.lvst i{width:9px;height:9px;border-radius:50%;background:var(--mut);display:inline-block}
.lvst.on i{background:#e0245e;box-shadow:0 0 0 3px rgba(224,36,94,.18)}
.lvst.on b{color:var(--fg)}
.alert{background:var(--alertbg);border:1px solid var(--alertbd);border-left:4px solid var(--alertbd);border-radius:8px;padding:12px 15px;margin:0 0 22px;font-size:14px}
.alert b{display:block;margin-bottom:3px}
.alert div{color:var(--mut);font-size:13px}
"""

PAGE = """<!doctype html><html lang=en><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Surveillance {day}</title>
<link rel=stylesheet href="{css}">
<div class=wrap id=top>
<div class=date>{day}</div>
<h1>{headline}</h1>
<p class=sub>{sub}</p>
{alert}
<div class=stats>
<div class=stat><b>{incidents}</b><span>incidents</span></div>
<div class=stat><b>{clips}</b><span>activity clips</span></div>
<div class=stat><b>{uniq}</b><span>clips reviewed</span></div>
<div class=stat><b>{coverage}</b><span>footage covers</span></div>
<div class=stat><b>{cam_stat}</b><span>{cam_stat_label}</span></div>
</div>
{live}

<h2>When it happened <span style="text-transform:none;letter-spacing:0;
font-weight:400">&mdash; click an hour to jump to it</span></h2>
<div class=tlwrap><div class=tl>{bars}</div></div>
{hourly}

<h2>What happened</h2>
{cards}

<h2>Cameras</h2>
<div>{chips}</div>

<h2>Hourly snapshot</h2>
<img class=sheet src="contact_sheet.jpg" alt="one frame per hour">

<footer>Generated {generated} &middot; {dupes} duplicate clips skipped
&middot; <a href="events.csv">events.csv</a>{drive}</footer>
</div>
</html>"""


LIVE_BLOCK = """<h2>Live now</h2>
<p class=lvst id=lvst><i></i><b>checking&hellip;</b></p>
<div class=live>
 <video id=lv playsinline muted autoplay controls preload=metadata></video>
 <div class=msg id=lvmsg>waiting for the first recorded segment&hellip;</div>
</div>
<p class=sub id=lvsub>Played from the NAS recording, a minute or two behind live.
 <a href="https://twitch.tv/__CH__" target="_blank" rel="noopener">Open on Twitch</a>
 for the true live feed.</p>
<script>
/* The Twitch player refuses to embed when parent= is a bare IP address, which
   is exactly how this page is served, so it rendered as a black box. Play our
   own recording instead: live_record.sh publishes the newest finished segment
   as /live/latest.mp4 and describes it in /live/latest.json. That is ~1-2 min
   behind the broadcast but needs nothing from Twitch, and it keeps working
   when Twitch drops the stream - which is the case this page exists for. */
(function(){
  var v=document.getElementById('lv'), msg=document.getElementById('lvmsg'),
      st=document.getElementById('lvst'), cur=0, tried=0, live=false;

  function ago(sec){
    if(sec<90) return Math.round(sec)+'s ago';
    if(sec<5400) return Math.round(sec/60)+' min ago';
    return (sec/3600).toFixed(1)+' h ago';
  }
  function say(live,txt){
    st.className='lvst'+(live?' on':'');
    st.innerHTML='<i></i><b>'+(live?'LIVE':'Offline')+'</b> &middot; '+txt;
  }
  /* Liveness comes from the recorder's own heartbeat, not from how old the
     newest segment is: ffmpeg can hold a dead socket for minutes, leaving a
     recent-looking file while nothing is actually arriving. */
  function poll(next){
    fetch('/live/status.json?t='+Date.now(),{cache:'no-store'})
      .then(function(r){return r.ok?r.json():null})
      .then(function(d){ live = !!(d && d.live && Date.now()/1000-d.at < 120) })
      .catch(function(){});
    fetch('/live/latest.json?t='+Date.now(),{cache:'no-store'})
      .then(function(r){return r.ok?r.json():null})
      .then(function(d){
        if(!d||!d.epoch){ if(!tried++) msg.textContent='no recording yet'; return }
        var age=Date.now()/1000-d.epoch;
        say(live, 'segment '+ago(age));
        if(d.epoch!==cur && (next||!cur)){
          cur=d.epoch; msg.style.display='none';
          v.src='/live/'+d.file+'?t='+d.epoch;
          v.play().catch(function(){});
        }
      })
      .catch(function(){ if(!tried++) msg.textContent='viewer cannot reach /live/'; });
  }
  /* When a segment finishes, roll straight on to whatever has landed since. */
  v.addEventListener('loadedmetadata', function(){
    if(v.videoWidth && v.videoHeight){
      v.parentNode.style.aspectRatio = v.videoWidth+' / '+v.videoHeight;
    }
  });
  v.addEventListener('ended', function(){ poll(true) });
  v.addEventListener('error', function(){ poll(true) });
  poll(true);
  setInterval(function(){ poll(false) }, 20000);
})();
</script>"""

HOUR_PAGE = """<!doctype html><html lang=en><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{day} {hh}</title>
<link rel=stylesheet href="{css}">
<div class=wrap id=top>
<div class=date>{day} &middot; {hh}</div>
<h1>{headline}</h1>
<p class=sub>{sub}</p>
<p class=nav>{nav}</p>
<div class=stats>
<div class=stat><b>{n}</b><span>incidents</span></div>
<div class=stat><b>{clips}</b><span>activity clips</span></div>
<div class=stat><b>{cams}</b><span>cameras</span></div>
</div>
<h2>What happened</h2>
<div class=grid>{cards}</div>
<h2>Cameras with activity</h2>
<div>{chips}</div>
{cams_block}
</div>
</html>"""

HOUR_INDEX = """<!doctype html><html lang=en><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{day} by hour</title>
<link rel=stylesheet href="{css}">
<div class=wrap id=top>
<div class=date>{day}</div>
<h1>Hour by hour</h1>
<p class=sub>{active} of 24 hours had activity.</p>
<p class=nav><a href="../summary.html">&larr; full day summary</a></p>
{rows}
</div>
</html>"""

#!/usr/bin/env python3


if __name__ == "__main__":
    days = sys.argv[1:] or sorted(os.listdir(os.path.join(BASE, "clips")))
    for d in days:
        build_day(d)
