#!/usr/bin/env python3
"""Can this camera join the house-camera mosaic?

The pipeline (start-stream.sh / stream.yml) pulls each camera DIRECTLY on the
LAN and never touches a vendor cloud, so a camera is usable only if it serves
    rtsp://   rtsps://   or   http://<ip>/<mjpeg path>
A camera whose picture exists only inside its phone app cannot be used at any
price.  This reports which, if any, it offers.

THREE DISTINCTIONS THIS TOOL MUST NOT BLUR
  refused  - the host is UP and actively says "no service on this port"
  timeout  - nothing is there at all, or a firewall is swallowing it
  open     - a service is listening
An earlier version collapsed refused and timeout into "closed" and told the
owner to return a brand-new Reolink that was simply not initialised yet.
A factory-fresh camera refuses 80 and 554 until its admin password is set,
while answering on its vendor port - which looks identical to a dead host
unless you keep the two apart.

EVERY probe is validated against a control first.  Several probes on this
estate silently reported "closed" for ports that are demonstrably open
(busybox has no nc, its sh has no /dev/tcp, Windows ping rejects -c), and a
checker that cannot fail honestly is worse than none.

ICMP is NOT used to decide anything: Reolink ships with ping disabled, so
"no reply" says nothing about whether the camera is alive.

usage:  camcheck.py <ip> [control_ip]
"""
import socket
import ssl
import sys
import re
import subprocess
import time

# Built from chr() deliberately: heredocs and shell quoting in this
# environment mangle backslash escapes, which corrupted an earlier version.
CRLF = chr(13) + chr(10)
BLANK = CRLF + CRLF

RTSP_PORTS = [554, 322, 8554, 10554]
HTTP_PORTS = [80, 8080, 81, 8081, 443]
# Vendor control/discovery ports. A camera answering here is ALIVE even when
# every streaming port refuses - which is the uninitialised case.
VENDOR_PORTS = {
    9000:  "Reolink device port",
    8000:  "Hikvision SDK / Reolink alt",
    37777: "Dahua SDK",
    34567: "XM / generic Chinese DVR",
    8899:  "generic ONVIF-ish",
}
MJPEG_PATHS = ["/video.cgi", "/videostream.cgi", "/mjpeg", "/video",
               "/video.mjpg", "/cgi-bin/mjpg/video.cgi",
               "/onvif/device_service"]
RTSP_PATHS = ["/stream0", "/stream1", "/stream2", "/live", "/live0", "/live1",
              "/h264", "/h264Preview_01_main", "/h264Preview_01_sub",
              "/h265Preview_01_main", "/ch0", "/ch1", "/video0", "/video1",
              "/Streaming/Channels/101", "/"]


def tcp_state(ip, port, to=3):
    """open | refused | timeout  - the distinction is the whole point."""
    s = socket.socket()
    s.settimeout(to)
    try:
        s.connect((ip, port))
        s.close()
        return "open"
    except ConnectionRefusedError:
        return "refused"
    except (socket.timeout, OSError):
        return "timeout"


def tcp(ip, port, to=3):
    return tcp_state(ip, port, to) == "open"


def _open(ip, port, tls):
    s = socket.create_connection((ip, port), timeout=6)
    if tls:
        c = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        c.check_hostname = False
        c.verify_mode = ssl.CERT_NONE
        s = c.wrap_socket(s, server_hostname=ip)
    return s


def _read_response(s, deadline=6.0):
    """Accumulate until the header block ends. ONE recv() IS NOT ENOUGH.

    The Wyze Cam Pan v3 emits its reply one token per TLS record: the first
    recv() returns exactly b'RTSP/1.0', the next b' ', then b'200'. Parsing a
    single read made a camera that answers perfectly well read as "tcp open
    but does not speak RTSP", and the checker then declared it unusable.
    Never assume a camera's reply arrives in one segment.
    """
    buf = b""
    end = time.time() + deadline
    while time.time() < end:
        s.settimeout(max(0.3, end - time.time()))
        try:
            chunk = s.recv(1600)
        except Exception:
            break
        if not chunk:
            break
        buf += chunk
        if BLANK.encode() in buf or len(buf) > 8192:
            break
        # A complete status line plus at least one header is enough tojudge a code.
        if buf.count(CRLF.encode()) >= 2:
            break
    return buf.decode("utf-8", "replace")


def rtsp_req(ip, port, tls, verb, path):
    scheme = "rtsps" if tls else "rtsp"
    url = "%s://%s:%d%s" % (scheme, ip, port, path)
    req = (verb + " " + url + " RTSP/1.0" + CRLF
           + "CSeq: 2" + CRLF
           + "Accept: application/sdp" + CRLF
           + "User-Agent: camcheck" + BLANK)
    try:
        s = _open(ip, port, tls)
        s.sendall(req.encode())
        d = _read_response(s)
        s.close()
    except Exception:
        return None, ""
    if not d.startswith("RTSP/"):
        return None, ""
    m = re.match("RTSP/1.0 ([0-9]+)", d)
    # Speaking RTSP without a parseable code still counts as speaking RTSP;
    # 0 is returned so callers see a truthy "it answered".
    return (int(m.group(1)) if m else 0), d


def find_paths(ip, port, tls):
    """401 = the path EXISTS and wants credentials.  404 = no such path."""
    out = []
    for path in RTSP_PATHS:
        code, _ = rtsp_req(ip, port, tls, "DESCRIBE", path)
        if code in (200, 401):
            out.append((path, code))
    return out


def http(ip, port, path):
    import urllib.request
    import urllib.error
    scheme = "https" if port == 443 else "http"
    url = "%s://%s:%d%s" % (scheme, ip, port, path)
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        r = urllib.request.urlopen(url, timeout=6, context=ctx)
        return r.status, r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, (e.headers.get("Content-Type", "") if e.headers else "")
    except Exception:
        return None, ""


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    ip = sys.argv[1]
    control = sys.argv[2] if len(sys.argv) > 2 else "192.168.1.31"

    print("=== probe validation (control %s:80 must read OPEN) ===" % control)
    if tcp_state(control, 80) != "open":
        print("   control %s:80 -> NOT OPEN" % control)
        print("   *** the probe itself is broken on this host. Results would be")
        print("   *** meaningless, so none are shown. Fix the probe first.")
        sys.exit(3)
    print("   control %s:80 -> OPEN, probe is trustworthy" % control)

    print("")
    print("=== %s : is anything there? ===" % ip)
    p = subprocess.run(["ping", "-c", "3", "-W", "3", ip],
                       capture_output=True, text=True)
    m = re.search("min/avg/max[^=]*= ([0-9.]+)/([0-9.]+)/([0-9.]+)", p.stdout)
    print("   ping: %s   (informational only - Reolink ships with ICMP off)"
          % ("avg %s ms" % m.group(2) if m else "no reply"))

    # A refusal anywhere proves the host is up, even with ICMP off and every
    # streaming service disabled.
    refused = []
    vendor_open = []
    rtsp_hits = []
    http_hits = []

    print("")
    print("=== RTSP ===")
    for port in RTSP_PORTS:
        st = tcp_state(ip, port)
        if st != "open":
            if st == "refused":
                refused.append(port)
            print("   :%-6s %s" % (port, st))
            continue
        spoke = False
        # Try the scheme this port conventionally carries first: 322 is rtsps
        # by convention, and plain RTSP there gets an immediate TCP reset.
        order = (True, False) if port == 322 else (False, True)
        for tls in order:
            code, body = rtsp_req(ip, port, tls, "OPTIONS", "/")
            if code is not None:
                realm = re.search('realm="([^"]+)"', body)
                print("   :%-6s %s speaks RTSP (OPTIONS -> %s)"
                      % (port, "rtsps" if tls else "rtsp ", code))
                rtsp_hits.append(("rtsps" if tls else "rtsp", port,
                                  realm.group(1) if realm else None))
                spoke = True
                break
        if not spoke:
            print("   :%-6s tcp open but does not speak RTSP" % port)

    print("")
    print("=== vendor control ports (an open one means ALIVE) ===")
    for port, name in sorted(VENDOR_PORTS.items()):
        st = tcp_state(ip, port)
        if st == "open":
            vendor_open.append((port, name))
            print("   :%-6s OPEN     %s" % (port, name))
        elif st == "refused":
            refused.append(port)
    if not vendor_open:
        print("   none open")

    print("")
    print("=== HTTP / MJPEG ===")
    for port in HTTP_PORTS:
        st = tcp_state(ip, port)
        if st != "open":
            if st == "refused":
                refused.append(port)
            continue
        for path in MJPEG_PATHS:
            code, ctype = http(ip, port, path)
            if code is None:
                continue
            tag = ""
            low = ctype.lower()
            if code in (200, 401) and ("mjpeg" in low or "multipart" in low):
                tag = "  <- MJPEG stream"
                http_hits.append((port, path, code))
            elif code == 401:
                tag = "  (exists, needs credentials)"
                http_hits.append((port, path, code))
            elif code == 200 and "onvif" in path:
                tag = "  <- ONVIF service"
                http_hits.append((port, path, code))
            print("   :%-5s %-30s %-4s %-26s%s"
                  % (port, path, code, ctype[:26], tag))

    print("")
    print("=== VERDICT ===")
    if rtsp_hits:
        sch, port, realm = rtsp_hits[0]
        print("   USABLE via RTSP.")
        if realm:
            print("   auth realm: %s" % realm)
        paths = find_paths(ip, port, sch == "rtsps")
        codes = set(c for _, c in paths)
        uninformative = len(paths) >= len(RTSP_PATHS) - 1 and len(codes) == 1
        if paths and not uninformative:
            print("   stream paths that exist (401 = present, needs creds):")
            for path, code in paths:
                print("     %-42s %s" % (path, code))
            if len(paths) > 1:
                print("   NOTE: %d paths answered. A dual-lens camera exposes"
                      % len(paths))
                print("   one per lens; the mosaic uses ONE pane per camera.")
            print("   camera-table line:")
            print('     ["<Name>"]="%s://<user>:${PASS}@%s:%d%s"'
                  % (sch, ip, port, paths[0][0]))
        elif uninformative:
            print("   path discovery NOT POSSIBLE: it answered %s for all %d"
                  % (codes.pop(), len(paths)))
            print("   paths tried, including bogus ones - it authenticates")
            print("   before routing, so a 401 proves nothing. Use the path")
            print("   from the camera's manual or app.")
            print('     ["<Name>"]="%s://<user>:${PASS}@%s:%d/<path>"'
                  % (sch, ip, port))
        print("   (Control Room = rtsps://...:322/stream0, known-working shape)")

    elif http_hits:
        port, path, code = http_hits[0]
        loc = path if port == 80 else ":%d%s" % (port, path)
        print("   PROBABLY USABLE via HTTP/MJPEG:")
        print('     ["<Name>"]="http://admin:${CAM_PASS}@%s%s"' % (ip, loc))

    elif vendor_open:
        port, name = vendor_open[0]
        print("   CAMERA DETECTED BUT NOT YET SET UP - do NOT return it.")
        print("   :%d is open (%s) while the streaming ports refuse." % (port, name))
        print("   A factory-fresh camera keeps HTTP and RTSP off until its")
        print("   admin password is set. Initialise it first:")
        if port in (9000, 8000):
            print("     Reolink Client for Windows (or the app) finds it on")
            print("     the LAN via this port - no cloud account needed.")
            print("     Set the admin password, then enable RTSP under")
            print("     Network > Advanced > Server Settings.")
        print("   Then run this checker again - 554 should be open.")

    elif refused:
        print("   HOST IS UP but every camera service refused the connection.")
        print("   Refused (not timed out) on: %s"
              % ", ".join(str(p) for p in sorted(set(refused))))
        print("   That means something is answering at this address but is")
        print("   not serving video. Either it is not a camera, or it is not")
        print("   set up yet. Check the vendor app before concluding anything.")

    else:
        print("   NOTHING AT THIS ADDRESS - every port timed out.")
        print("   Not necessarily a bad camera: it may be unplugged, on")
        print("   another subnet, or still booting. This is NOT evidence that")
        print("   a camera is app/cloud-only - only a live host that refuses")
        print("   or ignores RTSP and HTTP would show that.")

    print("")
    print("   The camera table lives in THREE files, which must move together:")
    print("     start-stream.sh")
    print("     .github/workflows/stream.yml")
    print("     notify_offline_cameras.py   <- the one that gets forgotten")


main()
