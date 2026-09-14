# Investigation brief — backyard fence top bar: when and why did it fall?

**For:** Gemini AI
**Incident:** The top bar on the left side of the backyard fence fell onto the grass.
**Goal:** Determine **WHEN** it fell and **WHY** (person, animal, wind, or structural failure).

Read section 2 before starting. Several non-obvious properties of this footage have already
produced wrong answers, and one of them will waste hours if you do not know it.

---

## 1. What is already established — do not re-derive

| when (burnt-in clock) | what | evidence |
|---|---|---|
| **Sep 8, 15:16:59 - 15:17:14** | **The owner repairs the bar.** Appears in the yard, reaches up at the fence post, crouches, leaves. | Balcony camera, https://www.twitch.tv/videos/2869045683 at +32s to +34s. Confirmed by the owner. |
| Sep 8, 18:28:58 | The wife of the owner, checking the garden. **Unrelated — exclude.** | Backyard camera, https://www.twitch.tv/videos/2869198849 at +2s |

**Therefore the bar fell BEFORE Sep 8 15:16:59.** That is a hard upper bound. Your task is to
find how much earlier, and why.

### Camera availability — this decides where you can even look

The **Backyard** camera is the only one that sees the fence clearly. Uptime:

- **Sep 6** — online all day
- **Sep 7** — online all day
- **Sep 8** — online early morning, confirmed present at 06:55 and 07:45
- **Sep 8 mid-morning** — drops offline, somewhere between 07:45 and 09:34
- **Sep 8, about 15:23** — comes back online, six minutes AFTER the repair

So for the hours immediately before the repair there is **no Backyard view at all**. Only the
Balcony camera covers that period, and it looks down obliquely through heavy tree cover, where
the fence is small, shadowed and partly hidden. **Do not try to judge the state of the bar from
the Balcony camera.** Use Balcony only to detect people and animals.

### Periods with NO footage whatsoever — 10.4 hours

| from | to | duration |
|---|---|---|
| Sep 6 02:55 | Sep 6 03:44 | 49 min |
| **Sep 6 19:11** | **Sep 6 21:05** | **114 min** |
| Sep 7 02:55 | Sep 7 05:11 | 136 min |
| **Sep 7 11:03** | **Sep 7 14:27** | **204 min** |
| Sep 7 20:18 | Sep 7 21:08 | 50 min |
| Sep 8 02:57 | Sep 8 04:05 | 68 min |

If your bracket lands inside one of these, **that is the answer** — report it as such. It is a
real finding, not a failure.

---

## 2. Critical properties of this footage

### 2.1 The burnt-in clock is the only trustworthy time

Every frame has a clock burnt into the top-left pane, e.g. `Office 2026-09-08 14:56:14`.
**Use it.** The Twitch publish time of a clip runs about **6 minutes ahead** of it, because the
system records segments, combines them, then streams. Never quote a time from the VOD listing.

### 2.2 Time inside a clip is NOT monotonic

Verified example, clip `2869045683`:

```
+33s -> clock 15:17:08
+34s -> clock 15:17:14
+35s -> clock 15:15:19     <-- jumps BACKWARDS almost two minutes
+36s -> clock 15:17:58
```

The recorder writes 60-second segments and the streamer concatenates whatever files are on
disk, not strictly in order. Consequences:

- You **cannot** binary-search by clip number or by offset and assume time increases.
- Read the clock **on every frame you extract**. Never interpolate it.

### 2.3 The stream SAMPLES reality, it does not cover it

Within one 23-second clip the clock advanced from `18:28:58` to `18:34:45` — nearly six real
minutes. The pipeline captures a segment, encodes it, then captures again; the time in between
is never recorded. There are gaps between essentially every segment, on top of the six long
gaps listed in section 1.

**So absence of evidence is not evidence of absence.** A fence bar falling takes about a second
and can easily land entirely in an unrecorded gap. If you find nothing, report that the event
was not captured. Do not conclude that nothing happened.

### 2.4 The camera layout changes, and panes move

The mosaic is rebuilt from whichever cameras are online.

**Six cameras, 3 across and 2 down, frame is 1280x480:**

| pane | region (x1,y1)-(x2,y2) |
|---|---|
| Office | (0,0)-(426,240) |
| Front | (426,0)-(852,240) |
| Kitchen | (852,0)-(1280,240) |
| **Balcony** | **(0,240)-(426,480)** |
| **Backyard** | **(426,240)-(852,480)** |
| Basement | (852,240)-(1280,480) |

**Five cameras, Backyard missing:**

| pane | region (x1,y1)-(x2,y2) |
|---|---|
| Office | (0,0)-(426,240) |
| Front | (426,0)-(852,240) |
| Kitchen | (852,0)-(1280,240) |
| **Balcony** | **(0,240)-(640,480)** |
| Basement | (640,240)-(1280,480) |

Every pane carries its name in its own top-left corner. **Identify panes by reading that label
on the frame in front of you.** Position alone will mislead you. Brightness heuristics for
detecting the layout were tried and are unreliable.

### 2.5 The Backyard camera can physically pan

It is a Wyze Cam Pan v3. Framing genuinely differs between Sep 6 and Sep 7-8. A shift in
framing is **not** evidence of anything. Compare the fence structure itself, not where it sits
in the frame.

---

## 3. Source material

Public Twitch VODs on channel **elarathornfield168**. The companion file
**sep6_to_sep8_1700_vods.csv** lists every clip from Sep 6 00:00 to Sep 8 17:00 Pacific:
**4,732 clips, about 40.5 hours**, with columns
`start_pacific, end_pacific, duration_sec, video_id, url`.

Extract a frame from any clip:

```
yt-dlp -g "https://www.twitch.tv/videos/<id>"        # prints an .m3u8 URL
ffmpeg -ss <seconds> -i "<that m3u8 URL>" -frames:v 1 -y out.jpg
```

---

## 4. Method that works

Two approaches were tried. **Use the second.**

**Median-background subtraction FAILS here.** Sunlight moves across the yard over hours, so the
top-ranked frames were simply the brightest and darkest ones. It found nothing useful.

**Neighbour differencing WORKS.** Compare each sampled frame against the average of the frame
before and the frame after. Slow lighting drift cancels out, and anything transient such as a
person or an animal spikes. This is what located both people in section 1.

```python
import cv2, glob, os, numpy as np

files = sorted(glob.glob('frames/p_*.jpg'))
imgs, keep = [], []
for f in files:
    a = cv2.imread(f)
    if a is None:
        continue
    pane = a[240:480, 426:852]          # Backyard, six-camera layout
    imgs.append(cv2.GaussianBlur(pane, (5,5), 0).astype(np.float32))
    keep.append(f)

scores = []
for i in range(1, len(imgs)-1):
    neighbour = (imgs[i-1] + imgs[i+1]) / 2.0
    diff = np.abs(imgs[i] - neighbour).mean(axis=2)
    roi = diff[60:240, 40:426]          # lawn and fence; skip static clutter at the edge
    scores.append((float((roi > 40).mean()*100), keep[i]))

scores.sort(reverse=True)
for pct, f in scores[:15]:
    print(os.path.basename(f), round(pct, 2))
```

Rank by the **percentage of pixels changed**, not by the mean. The mean is dominated by
lighting. A person typically scores 1.5 percent or higher; below about 0.8 percent is foliage.

**Sample every 2 minutes, not every 30.** At 2-minute spacing the owner appeared in exactly one
frame. A 30-minute sweep was tried first and missed both people entirely.

---

## 5. Search order

Work backwards from the known upper bound. Priority:

1. **Sep 8, 06:00 to 15:17** — the hours right before the repair. Backyard camera until it
   drops out mid-morning, Balcony only after that, and Balcony is for spotting people, not for
   judging the bar.
2. **Sep 7, full daylight** — Backyard camera up all day. Best chance of seeing both the fence
   state and a cause.
3. **Sep 6, from 12:53 onward** — Backyard up all day.

For each candidate the scan surfaces, extract several consecutive seconds around it, read the
clock on each frame, and view them before judging.

---

## 6. Cautions

- Light changes enormously through each day. Deep shade is not damage.
- Trees move constantly. Motion near the fence is not by itself a cause.
- The fence is small in frame. Upscale before judging: at native size a missing rail reads as a
  shadow line. Two independent attempts to call the state of the bar by eye from single frames
  were inconclusive, so prefer a clear before and after pair taken at the same time of day.
- Do not force a conclusion. "It fell somewhere in this 3-hour blind gap" is a far more useful
  answer than a confident guess.

---

## 7. What to report

1. **When it fell** — burnt-in clock, Pacific, as precise as the footage supports.
2. **Evidence** — clip URL plus offset for the last frame with the bar UP and the first with it
   DOWN, each with the clock you read on that frame.
3. **Why** — person, animal, wind, or structural failure, with what you actually saw. If a
   person, describe them. Do not guess identity.
4. **Confidence**, and what would raise it.
5. If undetermined: the **narrowest bracket** you established, and which blind gaps remain
   possible.
