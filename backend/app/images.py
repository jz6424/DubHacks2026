"""Club photos for swipe cards: one image per club (campus + normalized name), found on the club's own pages
(og:image, twitter:image, a large touch icon), downscaled to a JPEG and stored once under data/huskymatch/images, so
every student sees the same club profile. URLs come from the model and the web, so every fetch is SSRF-guarded:
http(s) only, no proxies, and each connection (redirects included) must resolve to public IPs only.

Backfill existing catalog clubs and jobs:  python -m app.images backfill [job_id ...]
"""
import hashlib
import io
import ipaddress
import json
import re
import socket
import sqlite3
import sys
import threading
import time
import traceback
import http.client
import urllib.request
from contextlib import closing
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from PIL import Image

from .catalog import norm
from .config import CATALOG_DB, CATALOG_MAX_AGE_DAYS, IMAGES, JOBS

TIMEOUT = 5
HTML_CAP = 1_500_000
IMAGE_CAP = 3_000_000
MAX_WIDTH = 800
MIN_SIDE = 100  # smaller is a favicon, not a profile picture
MAX_PAGES = 4
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}  # never SVG: it can carry script
Image.MAX_IMAGE_PIXELS = 25_000_000  # Pillow refuses images over twice this (decompression bombs)

# Only pages the club itself controls: elsewhere og:image is a site banner, a department logo or a news photo that
# may not be this club (a first test run picked up the UW "W", an iSchool logo and another school's mascot).
SKIP_HOSTS = ("instagram.com", "facebook.com", "linkedin.com", "reddit.com", "twitter.com", "x.com", "tiktok.com",
              "youtube.com", "discord.gg", "discord.com", "asuw.org")  # login walls and directories
UW_DOMAINS = ("uw.edu", "washington.edu")
UW_CLUB_HOSTS = ("sites.uw.edu", "students.washington.edu", "depts.washington.edu")  # each path is its own site
CLUB_PAGE_HOSTS = ("linktr.ee", "wixsite.com", "squarespace.com", "github.io", "weebly.com", "wordpress.com",
                   "sites.google.com", "carrd.co")
GENERIC_IMAGES = ("linktr.ee/profiles/_next/static/logo-assets",)  # a host's default image, not the club's

SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    campus TEXT NOT NULL, key TEXT NOT NULL, file TEXT NOT NULL, source_page TEXT NOT NULL, image_url TEXT NOT NULL,
    fetched_at REAL NOT NULL, PRIMARY KEY (campus, key));
"""

_key_locks: dict[tuple[str, str], threading.Lock] = {}
_locks_lock = threading.Lock()
_slots = threading.Semaphore(3)  # small VM: a few downloads at a time


class Refused(Exception):
    pass


# --- SSRF-safe fetching -------------------------------------------------------------------------------------------

def _public_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
    """socket.create_connection, but only to a host whose every address is public (checked at connect time, so
    redirects and DNS tricks are covered too)."""
    host, port = address
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    ips = [info[4][0] for info in infos]
    if not ips or not all(ipaddress.ip_address(ip.split("%")[0]).is_global for ip in ips):
        raise Refused(f"non-public address for {host}")
    err = None
    for family, socktype, proto, _, sockaddr in infos:
        sock = socket.socket(family, socktype, proto)
        try:
            sock.settimeout(timeout if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT else TIMEOUT)
            sock.connect(sockaddr)  # the address we checked, not a fresh lookup
            return sock
        except OSError as e:
            sock.close()
            err = e
    raise err or OSError(f"couldn't connect to {host}")


class _HTTPConnection(http.client.HTTPConnection):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._create_connection = _public_connection


class _HTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._create_connection = _public_connection


class _HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_HTTPConnection, req)


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_HTTPSConnection, req, context=self._context)


def _opener() -> urllib.request.OpenerDirector:
    """Only http/https (no file:, ftp:, data:), no environment proxies; redirects stay on http(s)."""
    op = urllib.request.OpenerDirector()
    for h in (urllib.request.ProxyHandler({}), _HTTPHandler(), _HTTPSHandler(), urllib.request.HTTPRedirectHandler(),
              urllib.request.HTTPDefaultErrorHandler(), urllib.request.HTTPErrorProcessor()):
        op.add_handler(h)
    return op


def fetch(url: str, cap: int, accept: str) -> tuple[bytes, str, str]:
    """(body, content type, final URL). Raises on anything unsafe, too big or not 2xx."""
    if urlparse(url).scheme not in ("http", "https"):
        raise Refused(f"not http(s): {url[:80]}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; MeAndUDub/1.0; club photos)",
                                               "Accept": accept})
    with _opener().open(req, timeout=TIMEOUT) as resp:
        if urlparse(resp.geturl()).scheme not in ("http", "https"):
            raise Refused("redirected off http(s)")
        body = resp.read(cap + 1)
        if len(body) > cap:
            raise Refused("too large")
        ctype = (resp.headers.get_content_type() or "").lower()
        return body, ctype, resp.geturl()


# --- finding an image on a page -----------------------------------------------------------------------------------

class _Meta(HTMLParser):
    def __init__(self):
        super().__init__()
        self.og, self.twitter, self.icons = [], [], []  # icons: (size, url)

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            name = (a.get("property") or a.get("name") or "").lower()
            if name in ("og:image", "og:image:secure_url", "og:image:url") and a.get("content"):
                self.og.append(a["content"])
            elif name in ("twitter:image", "twitter:image:src") and a.get("content"):
                self.twitter.append(a["content"])
        elif tag == "link" and a.get("href"):
            rel = a.get("rel", "").lower()
            if "apple-touch-icon" in rel or rel.split() == ["icon"]:
                sizes = [int(n) for n in re.findall(r"(\d+)x\d+", a.get("sizes", ""))]
                size = max(sizes) if sizes else (180 if "apple-touch-icon" in rel else 0)
                if size >= 120:
                    self.icons.append((size, a["href"]))


def candidates(html: str, base: str) -> list[str]:
    p = _Meta()
    try:
        p.feed(html)
    except Exception:  # noqa: BLE001 - broken HTML still may have yielded tags
        pass
    found = p.og + p.twitter + [u for _, u in sorted(p.icons, reverse=True)]
    return list(dict.fromkeys(urljoin(base, u.strip()) for u in found if u.strip()))


def _on(host: str, domains) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def _usable_page(url: str, website_host: str) -> bool:
    """A page the club controls: its own website's host, a UW club-hosting site, or a club page builder. Never a
    department/UW page (their og:image is the department's), a news article or a login wall."""
    host = (urlparse(url).hostname or "").lower()
    if not host or _on(host, SKIP_HOSTS):
        return False
    if _on(host, UW_DOMAINS):
        return host in UW_CLUB_HOSTS
    return host == website_host or _on(host, CLUB_PAGE_HOSTS)


def pages_for(card: dict) -> list[str]:
    """Club's own website first, then its other sources in card-link order, keeping only pages the club controls."""
    website = (card.get("links") or {}).get("website", "").strip()
    website_host = (urlparse(website).hostname or "").lower()
    urls = [website] + [s.get("url", "") for s in card.get("sources") or []]
    out = [u for u in dict.fromkeys(u.strip() for u in urls if u) if u.startswith(("http://", "https://"))
           and _usable_page(u, website_host)]
    return out[:MAX_PAGES]


def to_jpeg(body: bytes) -> bytes:
    """Decode (proves it's a real image), flatten, downscale to MAX_WIDTH and re-encode as JPEG."""
    with Image.open(io.BytesIO(body)) as im:
        if im.format not in ("JPEG", "PNG", "WEBP", "GIF"):
            raise Refused(f"unexpected format {im.format}")
        im.seek(0)
        if min(im.size) < MIN_SIDE:
            raise Refused(f"too small {im.size}")
        im = im.convert("RGBA")
        flat = Image.new("RGB", im.size, (255, 255, 255))
        flat.paste(im, mask=im.split()[3])
        if flat.width > MAX_WIDTH:
            flat = flat.resize((MAX_WIDTH, round(flat.height * MAX_WIDTH / flat.width)), Image.LANCZOS)
        out = io.BytesIO()
        flat.save(out, "JPEG", quality=82, optimize=True, progressive=True)
        return out.getvalue()


def find_image(card: dict, taken: set[str]) -> tuple[bytes, str, str] | None:
    """(jpeg, source page, image URL) for the first usable image on the club's pages, or None. Images already used by
    another club (`taken`) are skipped: a shared one is a site banner, not this club's."""
    for page in pages_for(card):
        try:
            body, ctype, final = fetch(page, HTML_CAP, "text/html,application/xhtml+xml")
            if "html" not in ctype:
                continue
            for img_url in candidates(body.decode("utf-8", "replace"), final)[:4]:
                if img_url in taken or any(g in img_url for g in GENERIC_IMAGES):
                    continue
                try:
                    data, itype, _ = fetch(img_url, IMAGE_CAP, "image/jpeg,image/png,image/webp,image/gif")
                    if itype not in IMAGE_TYPES:
                        continue
                    return to_jpeg(data), page, img_url
                except Exception:  # noqa: BLE001 - try the next candidate
                    continue
        except Exception:  # noqa: BLE001 - try the next page
            continue
    return None


# --- storage ------------------------------------------------------------------------------------------------------

def _db() -> sqlite3.Connection:
    CATALOG_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(CATALOG_DB, timeout=10)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con


def url_for(file: str) -> str:
    return f"/api/images/{file}" if file else ""


def lookup(campus: str, names: list[str]) -> dict[str, str]:
    """normalized name -> image URL, for the clubs that have one."""
    keys = list({norm(n) for n in names if n})
    if not keys:
        return {}
    with closing(_db()) as con:
        rows = con.execute(f"SELECT key, file FROM images WHERE campus = ? AND file != '' AND key IN "
                           f"({','.join('?' * len(keys))})", (campus, *keys)).fetchall()
    return {k: url_for(f) for k, f in rows}


def _lock_for(campus: str, key: str) -> threading.Lock:
    with _locks_lock:
        return _key_locks.setdefault((campus, key), threading.Lock())


def ensure(campus: str, card: dict) -> str:
    """The club's image URL, fetching it once if needed ("" if none was found; retried after CATALOG_MAX_AGE_DAYS)."""
    key = norm(card.get("name", ""))
    if not key:
        return ""
    with _lock_for(campus, key):
        with closing(_db()) as con:
            row = con.execute("SELECT file, fetched_at FROM images WHERE campus = ? AND key = ?",
                              (campus, key)).fetchone()
            if row and (row[0] or time.time() - row[1] < CATALOG_MAX_AGE_DAYS * 86400):
                return url_for(row[0])
            taken = {r[0] for r in con.execute("SELECT image_url FROM images WHERE image_url != '' AND NOT "
                                               "(campus = ? AND key = ?)", (campus, key))}
        with _slots:
            found = find_image(card, taken)
        file, page, img_url = "", "", ""
        if found:
            data, page, img_url = found
            file = f"{campus}-{key}-{hashlib.sha256(data).hexdigest()[:8]}.jpg"  # content hash: safe to cache forever
            IMAGES.mkdir(parents=True, exist_ok=True)
            tmp = IMAGES / (file + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(IMAGES / file)
        with closing(_db()) as con, con:
            con.execute("INSERT OR REPLACE INTO images VALUES (?,?,?,?,?,?)",
                        (campus, key, file, page, img_url, time.time()))
        return url_for(file)


def ensure_async(campus: str, card: dict) -> None:
    def run():
        try:
            ensure(campus, card)
        except Exception:  # noqa: BLE001 - a missing photo must never affect research
            traceback.print_exc()
    threading.Thread(target=run, daemon=True).start()


def backfill(job_ids: list[str]) -> None:
    """Fetch images for every catalog club and every card in the given jobs (default: all jobs)."""
    from .catalog import _db as catalog_db  # noqa: PLC0415
    with closing(catalog_db()) as con:
        clubs = [(campus, json.loads(card)) for campus, card in con.execute("SELECT campus, card FROM clubs")]
    from .jobs import job_files, read_job  # noqa: PLC0415
    paths = [JOBS / f"{j}.json" for j in job_ids] if job_ids else job_files()
    for p in paths:
        job = read_job(p)
        if not job:
            print(f"skipped {p.name}: not a readable job file")
            continue
        campus = job["profile"].get("campus") or "seattle"
        clubs += [(campus, c) for c in job["cards"]]
    seen = set()
    for campus, card in clubs:
        if (campus, norm(card["name"])) in seen:
            continue
        seen.add((campus, norm(card["name"])))
        url = ensure(campus, card)
        print(f"{'🖼 ' if url else '— '} {card['name'][:50]:52} {url}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["backfill"]:
        backfill(sys.argv[2:])
    else:
        print(__doc__)
