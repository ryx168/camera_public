#!/usr/bin/env python3
"""
Assemble the GitHub Pages site from the self-contained day pages.

A runner cannot host anything - it is ephemeral and has no public address - so
the pages are published as static files instead. Each day is already a single
self-contained HTML (stylesheet and thumbnails inlined), which is exactly what
a static host wants.

Recent days are pulled back from Drive so the site keeps history rather than
showing only the day this run happened to build.
"""
import os
import re
import sys
import shutil
import datetime
import subprocess

BASE = os.environ.get("ARCHIVE_BASE", os.path.abspath("archive"))
REMOTE = os.environ.get("RCLONE_REMOTE", "gdrive:camera_archive")
SITE = os.environ.get("SITE_DIR", os.path.abspath("site"))
KEEP_DAYS = int(os.environ.get("SITE_DAYS", "14"))

RCLONE_NET = ["--contimeout", "20s", "--timeout", "300s",
              "--low-level-retries", "3", "--retries", "2"]

PAGE = """<!doctype html><html lang=en><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Camera summaries</title>
<style>
:root{{color-scheme:light}}
body{{margin:0;font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;
background:#fbfaf8;color:#1a1a1a}}
.wrap{{max-width:760px;margin:0 auto;padding:40px 22px 64px}}
h1{{font-size:26px;margin:0 0 4px}}
p.sub{{color:#6b6b6b;margin:0 0 28px}}
a.day{{display:flex;justify-content:space-between;align-items:center;
gap:12px;padding:14px 16px;margin-bottom:8px;border:1px solid #e6e2db;
border-radius:10px;background:#fff;text-decoration:none;color:inherit}}
a.day:hover{{border-color:#c9c2b6}}
a.day b{{font-weight:600}}
a.day span{{color:#6b6b6b;font-size:13px}}
footer{{margin-top:32px;color:#8a8a8a;font-size:12px}}
</style>
<div class=wrap>
<h1>Camera summaries</h1>
<p class=sub>{n} day{s} &middot; updated {when}</p>
{rows}
<footer>Each page is self-contained &mdash; open it, or save it and it still
works offline. Footage itself is not published here.</footer>
</div>
</html>"""


def run(cmd):
    return subprocess.run(cmd, capture_output=True)


def collect():
    """Bring recent day pages together into the site directory."""
    os.makedirs(SITE, exist_ok=True)
    cutoff = (datetime.date.today()
              - datetime.timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")

    # Whatever this run just produced locally.
    local = os.path.join(BASE, "daily")
    if os.path.isdir(local):
        for day in os.listdir(local):
            src = os.path.join(local, day, "summary", "summary-%s.html" % day)
            if os.path.exists(src) and day >= cutoff:
                shutil.copy2(src, os.path.join(SITE, "%s.html" % day))

    # Earlier days from Drive, so the site keeps history rather than showing
    # only today. Copied one day at a time with copyto: rclone has no flag to
    # flatten a tree, and this names each file exactly as the site wants it.
    for d in days_on_drive():
        if d < cutoff:
            continue
        dst = os.path.join(SITE, "%s.html" % d)
        if os.path.exists(dst):
            continue
        run(["rclone", "copyto",
             "%s/daily/%s/summary/summary-%s.html" % (REMOTE, d, d),
             dst] + RCLONE_NET)

    # Normalise anything that arrived as summary-<day>.html
    for f in list(os.listdir(SITE)):
        m = re.match(r"summary-(\d{4}-\d{2}-\d{2})\.html$", f)
        if m:
            os.replace(os.path.join(SITE, f),
                       os.path.join(SITE, "%s.html" % m.group(1)))

    # Drop anything past the window.
    for f in list(os.listdir(SITE)):
        m = re.match(r"(\d{4}-\d{2}-\d{2})\.html$", f)
        if m and m.group(1) < cutoff:
            os.remove(os.path.join(SITE, f))

    return sorted((f[:-5] for f in os.listdir(SITE)
                   if re.match(r"\d{4}-\d{2}-\d{2}\.html$", f)), reverse=True)


def days_on_drive():
    r = run(["rclone", "lsf", "--dirs-only", "%s/daily" % REMOTE] + RCLONE_NET)
    if r.returncode != 0:
        return []
    return [d.strip("/") for d in r.stdout.decode("utf-8", "replace").split()
            if re.match(r"^\d{4}-\d{2}-\d{2}/?$", d.strip())]


def main():
    days = collect()
    if not days:
        print("no day pages to publish")
        return 1

    rows = []
    for d in days:
        size = os.path.getsize(os.path.join(SITE, "%s.html" % d)) / 1e6
        label = datetime.datetime.strptime(d, "%Y-%m-%d").strftime(
            "%a %d %B %Y")
        rows.append('<a class=day href="%s.html"><b>%s</b>'
                    '<span>%.1f MB</span></a>' % (d, label, size))

    with open(os.path.join(SITE, "index.html"), "w", encoding="utf-8") as f:
        f.write(PAGE.format(
            n=len(days), s="" if len(days) == 1 else "s",
            when=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            rows="\n".join(rows)))

    # Public, but there is no reason to be in search results.
    with open(os.path.join(SITE, "robots.txt"), "w", encoding="utf-8") as f:
        f.write("User-agent: *\nDisallow: /\n")

    print("site: %d day page(s) -> %s" % (len(days), SITE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
