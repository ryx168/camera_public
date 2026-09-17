#!/usr/bin/env python3
"""
Fold a day's report into one self-contained HTML file.

Google Drive stopped hosting HTML in 2016: opening summary.html there gives a
download prompt or raw source, and even downloaded it is useless on its own
because the stylesheet and every thumbnail are separate files beside it.

This writes summary-<day>.html with the stylesheet inlined and every image
embedded as a data URI - one file that opens anywhere, with no NAS, no network
and no folder structure around it.

What cannot come along is rewritten rather than left broken:

  * the "Live now" tile polled the NAS. On a real domain the Twitch player
    embeds fine - Twitch only refuses a bare IP as parent=, which is what the
    NAS was - so the live stream is offered there, with the most recent mosaic
    frame as the fallback for a saved copy
  * incident cards link to activity/*.mp4, which are tens of gigabytes and
    stay on Drive - each card is repointed at that clip's Drive file, so
    clicking a thumbnail still plays the footage
  * hour pages are separate files, so those links go too
"""
import os
import re
import sys
import json
import base64
import datetime

BASE = os.environ.get("ARCHIVE_BASE", os.path.abspath("archive"))
# Refuse to emit something an inbox or Drive preview will choke on.
MAX_MB = float(os.environ.get("STANDALONE_MAX_MB", "40"))
CHANNEL = os.environ.get("TWITCH_CHANNEL", "elarathornfield168")


# A neutral tile, inline, for a thumbnail that could not be embedded. Never a
# relative URL - that 404s on a static host.
PLACEHOLDER = (
    "data:image/svg+xml;utf8,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' width='420' height='236'%3E"
    "%3Crect width='100%25' height='100%25' fill='%23efece7'/%3E"
    "%3Ctext x='50%25' y='50%25' dominant-baseline='middle' "
    "text-anchor='middle' font-family='system-ui,sans-serif' font-size='15' "
    "fill='%239a948c'%3Ethumbnail not in this copy%3C/text%3E%3C/svg%3E")


def data_uri(path):
    ext = os.path.splitext(path)[1].lower()
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".gif": "image/gif"}.get(ext, "image/jpeg")
    with open(path, "rb") as f:
        return "data:%s;base64,%s" % (
            mime, base64.b64encode(f.read()).decode("ascii"))


def build(day, drive_id=""):
    summ = os.path.join(BASE, "daily", day, "summary")
    src = os.path.join(summ, "summary.html")
    if not os.path.exists(src):
        print("no summary.html for %s" % day)
        return None
    html = open(src, encoding="utf-8").read()

    # ---- stylesheet ----
    css_path = os.path.join(summ, "style.css")
    if os.path.exists(css_path):
        css = open(css_path, encoding="utf-8").read()
        html = re.sub(r'<link[^>]*href="style\.css"[^>]*>',
                      "<style>\n%s\n</style>" % css, html, count=1)

    # ---- the live tile polls the NAS, so it cannot work on a static copy.
    # Rather than just removing it, put the most recent mosaic frame in its
    # place so the page still opens on "what the cameras last saw".
    latest = ""
    # build_daily writes these under summary/hours, not beside it.
    hours = os.path.join(summ, "hours")
    if os.path.isdir(hours):
        frames = sorted(f for f in os.listdir(hours) if f.endswith(".jpg"))
        if frames:
            slot = os.path.splitext(frames[-1])[0]
            label = "%s:%s" % (slot[:2], slot[2:]) if len(slot) == 4 else slot
            latest = ('<h2>Latest frame</h2>'
                      '<p class=sub>Mosaic at %s &mdash; a snapshot from the last '
                      'analysed slot.</p>'
                      '<img src="%s" alt="latest mosaic" '
                      'style="width:100%%;max-width:760px;border-radius:10px;'
                      'border:1px solid var(--line, #e6e2db)">'
                      % (label, data_uri(os.path.join(hours, frames[-1]))))
    # On a real domain the Twitch player CAN be embedded - the reason it never
    # worked from the NAS is that Twitch refuses a bare IP as parent=, and
    # ryx168.github.io is not one. So offer the live stream where it can work
    # and fall back to the still where it cannot (a downloaded copy on file://,
    # or any host Twitch will not accept).
    live = ('<h2>Live now</h2>'
            '<div id="lvbox" style="display:none;position:relative;'
            'aspect-ratio:8/3;max-width:760px;background:#000;'
            'border-radius:10px;overflow:hidden">'
            '<iframe id="lvfr" title="Live stream" allowfullscreen '
            'frameborder="0" scrolling="no" '
            'style="position:absolute;inset:0;width:100%%;height:100%%;'
            'border:0"></iframe></div>'
            '<div id="lvalt">%s</div>'
            '<script>(function(){'
            'var h=location.hostname;'
            # A hostname with a dot that is not an IPv4 literal. Twitch accepts
            # a domain and refuses a bare address - which is exactly why this
            # never worked when the page was served from the NAS.
            r'if(h&&h.indexOf(".")>0&&!/^\d+\.\d+\.\d+\.\d+$/.test(h)){'
            'document.getElementById("lvfr").src='
            '"https://player.twitch.tv/?channel=%s&muted=true&parent="'
            '+encodeURIComponent(h);'
            'document.getElementById("lvbox").style.display="block";'
            'document.getElementById("lvalt").style.display="none";}'
            '})();</script>'
            '<p class=sub>Live from Twitch when this page is opened on a '
            'website; a saved copy shows the snapshot instead. '
            '<a href="https://twitch.tv/%s" target="_blank" rel="noopener">'
            'Open on Twitch</a></p>'
            % (latest, CHANNEL, CHANNEL))
    # A plain string replacement would be parsed as a template and the \d in
    # the IPv4 test above would raise "bad escape". A function is passed
    # through untouched.
    html = re.sub(r"<h2>Live now</h2>.*?</script>", lambda _m: live, html,
                  flags=re.S, count=1)

    # ---- images become data URIs ----
    embedded, missing = 0, 0

    def embed(m):
        nonlocal embedded, missing
        rel = m.group(1)
        p = os.path.join(summ, rel)
        if os.path.exists(p):
            embedded += 1
            return 'src="%s"' % data_uri(p)
        # Leaving the original relative src here is the worst outcome: on a
        # static host it resolves to a URL that does not exist and the reader
        # gets a broken-image icon. An inline placeholder keeps the layout and
        # says plainly that the picture did not travel with the page.
        missing += 1
        return 'src="%s"' % PLACEHOLDER

    html = re.sub(r'src="((?:thumbs/|contact_sheet)[^"]*)"', embed, html)

    # ---- links ----
    # Cards point at activity/*.mp4, far too large to embed, so the clips stay
    # on Drive. Point each card at that clip's Drive file instead, so clicking
    # a thumbnail still plays the footage. A clip with no id becomes an inert
    # tile rather than a link that goes nowhere.
    ids = {}
    try:
        ids = json.load(open(os.path.join(summ, "activity_ids.json")))
    except Exception:
        pass
    linked, inert = [0], [0]

    def relink(m):
        fid = ids.get(m.group(1))
        if fid:
            linked[0] += 1
            return ('<a class=card target="_blank" rel="noopener" '
                    'href="https://drive.google.com/file/d/%s/view"' % fid)
        # An <a> with no href is inert but still closes with </a>, so a mix of
        # linked and unlinked cards cannot leave unbalanced tags.
        inert[0] += 1
        return "<a class=card"

    html = re.sub(r'<a class=card href="[^"]*?/([^"/]+\.mp4)"', relink, html)
    html = re.sub(r'<a class=top href="hourly/[^"]*"[^>]*>.*?</a>', "", html,
                  flags=re.S)
    html = re.sub(r'<a class=hourlink[^>]*>.*?</a>', "", html, flags=re.S)
    html = re.sub(r'&middot; <a href="events\.csv">events\.csv</a>', "", html)

    # ---- say where the footage is ----
    banner = (
        '<p style="margin:0 0 18px;padding:10px 14px;border-radius:8px;'
        'background:#fff6e5;border:1px solid #e8c789;font-size:14px">'
        'Offline copy &mdash; the clips are not embedded. ')
    if drive_id:
        banner += ('<a href="https://drive.google.com/drive/folders/%s" '
                   'target="_blank" rel="noopener">Open this day on Google '
                   'Drive</a> for the footage.' % drive_id)
    else:
        banner += "The footage is in this day's Google Drive folder."
    banner += "</p>"
    html = re.sub(r"(<div class=wrap id=top>)", r"\1" + banner, html, count=1)

    dst = os.path.join(summ, "summary-%s.html" % day)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(html)

    print("  cards: %d linked to Drive, %d without a clip id"
          % (linked[0], inert[0]))
    mb = os.path.getsize(dst) / 1e6
    print("standalone: %s (%.1f MB, %d images embedded%s)"
          % (os.path.basename(dst), mb, embedded,
             ", %d missing" % missing if missing else ""))
    if mb > MAX_MB:
        print("::warning::standalone page is %.1f MB, over the %g MB guide"
              % (mb, MAX_MB))
    return dst


if __name__ == "__main__":
    d = (sys.argv[1] if len(sys.argv) > 1
         else os.environ.get("DAY")
         or datetime.date.today().strftime("%Y-%m-%d"))
    sys.exit(0 if build(d, os.environ.get("DRIVE_FOLDER_ID", "")) else 1)
