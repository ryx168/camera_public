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

  * the "Live now" tile polls the NAS, so it is removed
  * incident cards link to activity/*.mp4, which are tens of gigabytes and stay
    on Drive - the cards become plain tiles and a single link at the top goes
    to the day's Drive folder
  * hour pages are separate files, so those links go too
"""
import os
import re
import sys
import base64
import datetime

BASE = os.environ.get("ARCHIVE_BASE", os.path.abspath("archive"))
# Refuse to emit something an inbox or Drive preview will choke on.
MAX_MB = float(os.environ.get("STANDALONE_MAX_MB", "40"))


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

    # ---- the live tile needs the NAS; drop it ----
    html = re.sub(r"<h2>Live now</h2>.*?</script>", "", html,
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
        missing += 1
        return m.group(0)

    html = re.sub(r'src="((?:thumbs/|contact_sheet)[^"]*)"', embed, html)

    # ---- links that cannot work offline ----
    # Cards point at activity/*.mp4. Those stay on Drive, so make the tile
    # inert rather than a dead link.
    html = re.sub(r'<a class=card href="[^"]*\.mp4"', "<span class=card", html)
    html = re.sub(r"</a>(\s*</div>\s*</section>)", r"</span>\1", html)
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
