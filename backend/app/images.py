"""Club media for swipe cards: up to 5 real photos (events, people, things they built) plus a logo per club (campus +
normalized name), found only on pages the club controls, re-encoded as JPEGs and stored once under
data/huskymatch/images, so every student sees the same club profile. A wrong photo is worse than none, so the rules
are strict. URLs come from the model and the web, so every fetch is SSRF-guarded: http(s) only, no proxies, and each
connection (redirects included) must resolve to public IPs only.

    python -m app.images backfill [--refetch] [job_id ...]   fetch media for catalog clubs and jobs (default: all)
    python -m app.images show [name filter]                  print chosen photos and logo per club, with sources
    python -m app.images sheet OUT.jpg [name filter]         contact sheet of the same, to eyeball quality
"""
import hashlib
import http.client
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
import urllib.request
import warnings
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from PIL import Image

from .catalog import norm
from .config import CATALOG_DB, CATALOG_MAX_AGE_DAYS, IMAGES, JOBS

TIMEOUT = 5
CLUB_BUDGET_S = 15  # all fetching for one club
HTML_CAP = 1_500_000
IMAGE_CAP = 3_000_000
MAX_PAGES = 4  # homepage + up to 3 linked pages (gallery, events, about, ...)
MAX_DOWNLOADS = 14  # photo candidates tried per club
MAX_LOGO_DOWNLOADS = 4  # logo candidates, on top (photos used to use up the budget before the logo was tried)
MAX_PHOTOS = 5
PHOTO_WIDTH, LOGO_WIDTH = 1000, 400
PHOTO_MIN_W, PHOTO_MIN_H = 400, 250
PHOTO_ASPECT = (0.5, 2.5)
PHOTO_MIN_COLORS = 900  # distinct colours in a 64x64 sample: photos have many, flat graphics and logos few
LOGO_MAX_COLORS = 450  # real logos measured 2-280; above this a "logo" was a banner or group photo
LOGO_MAX_COLORS_NAMED = 650  # when the image's name/alt names the club (e.g. a Linktree avatar on a gradient)
LOGO_MIN_SIDE = 100
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}  # never SVG: it can carry script
Image.MAX_IMAGE_PIXELS = 40_000_000  # Pillow refuses images over twice this (decompression bombs)
warnings.simplefilter("ignore", Image.DecompressionBombWarning)  # big photos are handled in decode()
FULL_DECODE_MAX = 12_000_000  # pixels; bigger JPEGs are decoded at reduced scale, other formats refused (small VM)

# Only pages the club itself controls: elsewhere og:image is a site banner, a department logo or a news photo that
# may not be this club (a first test run picked up the UW "W", an iSchool logo and another school's mascot).
SKIP_HOSTS = ("instagram.com", "facebook.com", "linkedin.com", "reddit.com", "twitter.com", "x.com", "tiktok.com",
              "youtube.com", "discord.gg", "discord.com", "asuw.org")  # login walls and directories
UW_DOMAINS = ("uw.edu", "washington.edu")
UW_CLUB_HOSTS = ("sites.uw.edu", "students.washington.edu", "depts.washington.edu")  # each path is its own site
CLUB_PAGE_HOSTS = ("linktr.ee", "wixsite.com", "squarespace.com", "github.io", "weebly.com", "wordpress.com",
                   "sites.google.com", "carrd.co")
SHARED_HOSTS = UW_CLUB_HOSTS + ("sites.google.com", "linktr.ee")  # one host, many sites: stay under the club's first path part

# Images that are never the club's own photo: host defaults, website themes, UW marketing stock, stock libraries.
GENERIC_IMAGES = ("linktr.ee/profiles/_next/static/logo-assets", "/wp-content/themes/", "/wp-content/plugins/",
                  "uw-s3-cdn", "/media/11062b_", "/media/nsplsh_", "gravatar.com",  # 11062b_/nsplsh_: Wix stock
                  "linktr.ee/_marketing", "/logo192.png", "/logo512.png")  # last two: React app defaults
STOCK_HOSTS = ("unsplash.com", "pexels.com", "pixabay.com", "placeholder.com", "placehold.co", "placehold.it",
               "picsum.photos", "lorempixel.com", "dummyimage.com", "shutterstock.com", "istockphoto.com",
               "gettyimages.com", "stock.adobe.com")

NOT_PHOTO = re.compile(r"logo|icon|favicon|sprite|badge|emoji|avatar|placeholder|banner[-_]?ad|qr[-_]?code|\bqr\b|"
                       r"spinner|loader|arrow|button|spacer|pixel|blank|tracking|signature|map[-_]|template|default|"
                       r"temp(?=[._-])", re.I)  # temp: e.g. lucytemp.jpg, a stand-in on an officer bio
LOGO_HINT = re.compile(r"logo|wordmark|crest|emblem|brand", re.I)
# Logos that aren't the club's: social links and sponsors (a test run picked up an Instagram icon and a sponsor logo).
OTHER_ORG = re.compile(r"instagram|facebook|twitter|linkedin|youtube|discord|tiktok|github|slack|venmo|paypal|"
                       r"sponsor|partner|google|microsoft|amazon|boeing|nasa|unp|unp[-_]", re.I)
NAME_STOP = {"uw", "the", "club", "university", "washington", "society", "association", "chapter", "student",
             "students", "and", "for", "of", "at", "on", "campus", "seattle", "bothell", "tacoma", "team", "group", "husky", "huskies", "dawgs", "lab"}
GOOD_HINT = re.compile(r"team|event|member|build|robot|competition|group|meeting|workshop|practice|tournament|"
                       r"race|trip|performance|show|project|volunteer|launch", re.I)
SUBPAGE = re.compile(r"galler|photo|event|about|team|project|our[-_ ]?work|media|who[-_ ]?we[-_ ]?are|members|"
                     r"officers|history|past", re.I)

SCHEMA = """
CREATE TABLE IF NOT EXISTS club_media (
    campus TEXT NOT NULL, key TEXT NOT NULL, photos TEXT NOT NULL, logo TEXT NOT NULL, fetched_at REAL NOT NULL,
    PRIMARY KEY (campus, key));
"""
# photos: JSON [{file, page, src}] best first; logo: JSON {file, page, src} or {}.

_key_locks: dict[tuple[str, str], threading.Lock] = {}
_locks_lock = threading.Lock()
_slots = threading.Semaphore(3)  # small VM: a few clubs at a time


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


def fetch(url: str, cap: int, accept: str, timeout: float = TIMEOUT) -> tuple[bytes, str, str]:
    """(body, content type, final URL). Raises on anything unsafe, too big or not 2xx."""
    if urlparse(url).scheme not in ("http", "https"):
        raise Refused(f"not http(s): {url[:80]}")
    if timeout <= 0.2:
        raise Refused("out of time")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; MeAndUDub/1.0; club photos)",
                                               "Accept": accept})
    with _opener().open(req, timeout=timeout) as resp:
        if urlparse(resp.geturl()).scheme not in ("http", "https"):
            raise Refused("redirected off http(s)")
        body = resp.read(cap + 1)
        if len(body) > cap:
            raise Refused("too large")
        return body, (resp.headers.get_content_type() or "").lower(), resp.geturl()


# --- which pages ---------------------------------------------------------------------------------------------------

def _on(host: str, domains) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def _usable_page(url: str, website_host: str) -> bool:
    """A page the club controls: its own website's host, a UW club-hosting site, or a club page builder. Never a
    department/UW page (their images are the department's), a news article or a login wall."""
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
    return [u for u in dict.fromkeys(u.strip() for u in urls if u) if u.startswith(("http://", "https://"))
            and _usable_page(u, website_host)]


def _same_site(url: str, home: str) -> bool:
    a, b = urlparse(url), urlparse(home)
    if (a.hostname or "").lower() != (b.hostname or "").lower():
        return False
    if (a.hostname or "").lower() in SHARED_HOSTS:  # sites.uw.edu/<club>/...: stay inside the club's site
        first = [p for p in b.path.split("/") if p][:1]
        return not first or [p for p in a.path.split("/") if p][:1] == first
    return True


# --- reading a page -------------------------------------------------------------------------------------------------

@dataclass
class Cand:
    url: str
    page: str
    kind: str  # og | twitter | img | bg | icon
    hint: str = ""  # filename + alt + class + id, for logo/photo keywords
    size: int = 0  # declared icon size
    in_header: bool = False  # inside <header>/<nav>, where a site's own logo lives


def _best_from_srcset(srcset: str) -> str:
    best, best_w = "", -1.0
    for part in srcset.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        w = 1.0
        if len(bits) > 1:
            m = re.match(r"([\d.]+)([wx])", bits[1])
            if m:
                w = float(m.group(1)) * (1000 if m.group(2) == "x" else 1)
        if (w <= 1600 and w > best_w) or best_w < 0:  # largest up to ~1600 px: big enough, under the size cap
            best, best_w = bits[0], w
    return best


class _Page(HTMLParser):
    def __init__(self, base: str):
        super().__init__()
        self.base, self.cands, self.links = base, [], []  # links: (url, text)
        self._a: list | None = None
        self._header = 0

    def _add(self, url: str, kind: str, hint: str = "", size: int = 0):
        url = (url or "").strip()
        if url and not url.startswith("data:"):
            full = urljoin(self.base, url)
            name = urlparse(full).path.rsplit("/", 1)[-1]
            self.cands.append(Cand(full, self.base, kind, f"{name} {hint}".strip(), size, self._header > 0))

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag in ("header", "nav"):
            self._header += 1
        if tag == "meta":
            name = (a.get("property") or a.get("name") or "").lower()
            if name in ("og:image", "og:image:secure_url", "og:image:url"):
                self._add(a.get("content", ""), "og")
            elif name in ("twitter:image", "twitter:image:src"):
                self._add(a.get("content", ""), "twitter")
        elif tag == "link" and a.get("href"):
            rel = a.get("rel", "").lower()
            if "apple-touch-icon" in rel or "icon" in rel.split():
                sizes = [int(n) for n in re.findall(r"(\d+)x\d+", a.get("sizes", ""))]
                self._add(a["href"], "icon", rel, max(sizes) if sizes else (180 if "apple" in rel else 0))
        elif tag in ("img", "source"):
            url = (_best_from_srcset(a.get("data-srcset") or a.get("srcset") or "")
                   or a.get("data-src") or a.get("data-lazy-src") or a.get("data-image") or a.get("src", ""))
            self._add(url, "img", " ".join(a.get(k, "") for k in ("alt", "class", "id", "title")))
        elif tag == "a" and a.get("href"):
            self._a = [urljoin(self.base, a["href"]), ""]
        style = a.get("style", "")
        if "background" in style:
            for m in re.finditer(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", style):
                self._add(m.group(1), "bg", " ".join(a.get(k, "") for k in ("class", "id")))

    def handle_data(self, data):
        if self._a is not None:
            self._a[1] += data

    def handle_endtag(self, tag):
        if tag in ("header", "nav") and self._header:
            self._header -= 1
        if tag == "a" and self._a is not None:
            self.links.append((self._a[0], " ".join(self._a[1].split())[:80]))
            self._a = None


def read_page(html: str, base: str) -> _Page:
    p = _Page(base)
    try:
        p.feed(html)
    except Exception:  # noqa: BLE001 - broken HTML still may have yielded tags
        pass
    return p


def subpages(page: _Page, home: str, n: int) -> list[str]:
    """Same-site pages whose path or link text looks like gallery / events / about / team / projects / media."""
    out = []
    for url, text in page.links:
        url = url.split("#")[0]
        path = urlparse(url).path
        if (url.startswith(("http://", "https://")) and _same_site(url, home) and url.rstrip("/") != home.rstrip("/")
                and not re.search(r"\.(pdf|jpe?g|png|gif|zip|docx?)$", path, re.I)
                and (SUBPAGE.search(path) or SUBPAGE.search(text)) and url not in out):
            out.append(url)
    return out[:n]


def _name_tokens(name: str) -> set[str]:
    """Distinctive words of a club's name (and its acronym), for telling its logo from a sponsor's."""
    words = re.findall(r"[a-z0-9]+", re.sub(r"[-–]", "", name.lower()))
    toks = {w for w in words if len(w) >= 3 and w not in NAME_STOP}
    toks |= {re.sub(r"[^a-z0-9]", "", m.lower()) for m in re.findall(r"\(([^)]+)\)", name)}
    return {t for t in toks if len(t) >= 3}


def sized(url: str) -> str:
    """Ask resizing CDNs for ~1000 px instead of the original (keeps downloads under the cap)."""
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if host.endswith("squarespace-cdn.com") or host.endswith("static1.squarespace.com"):
        return p._replace(query="format=1000w").geturl()
    if host == "static.wixstatic.com":
        m = re.match(r"/media/([^/]+)", p.path)
        if m:
            return f"https://static.wixstatic.com/media/{m.group(1)}/v1/fit/w_1000,h_1000,q_85/{m.group(1)}"
    return url


def _skip_image(url: str) -> bool:
    low = url.lower()
    host = (urlparse(low).hostname or "")
    return (not low.startswith(("http://", "https://")) or _on(host, STOCK_HOSTS)
            or any(g in low for g in GENERIC_IMAGES) or re.search(r"\.(svg|ico)(\?|$)", low) is not None)


# --- judging an image ------------------------------------------------------------------------------------------------

@dataclass
class Pic:
    im: Image.Image  # RGBA
    sha: str
    dhash: int
    colors: int
    clear: float  # fraction of (nearly) transparent pixels


def decode(body: bytes) -> Pic:
    with Image.open(io.BytesIO(body)) as src:
        if src.format not in ("JPEG", "PNG", "WEBP", "GIF"):
            raise Refused(f"unexpected format {src.format}")
        src.seek(0)
        if src.width * src.height > FULL_DECODE_MAX:
            if src.format != "JPEG":
                raise Refused(f"too many pixels {src.size}")
            src.draft("RGB", (src.width // 4, src.height // 4))  # decode at 1/2-1/8 scale: far less memory
        im = src.convert("RGBA")
    small = im.resize((64, 64))
    alpha = small.getchannel("A").getdata()
    clear = sum(1 for v in alpha if v < 16) / 4096
    colors = len({(r >> 3, g >> 3, b >> 3) for r, g, b, a in small.getdata() if a >= 16})
    g = im.convert("L").resize((9, 8))
    px = list(g.getdata())
    dh = 0
    for row in range(8):
        for col in range(8):
            dh = (dh << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
    return Pic(im, hashlib.sha256(body).hexdigest(), dh, colors, clear)


def is_photo(p: Pic) -> bool:
    w, h = p.im.size
    return (w >= PHOTO_MIN_W and h >= PHOTO_MIN_H and PHOTO_ASPECT[0] <= w / h <= PHOTO_ASPECT[1]
            and p.clear < 0.05 and p.colors >= PHOTO_MIN_COLORS)


def is_logo(p: Pic) -> bool:
    w, h = p.im.size
    return max(w, h) >= LOGO_MIN_SIDE and min(w, h) >= 32 and 0.25 <= w / h <= 4


def _near(a: int, b: int) -> bool:
    return bin(a ^ b).count("1") <= 6


def _backdrop(im: Image.Image) -> tuple[int, int, int]:
    """White, unless the visible pixels are mostly light (a white logo on transparency would vanish): then dark."""
    small = im.resize((64, 64))
    lum = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b, a in small.getdata() if a >= 128]
    clear = sum(1 for *_, a in small.getdata() if a < 16) / 4096
    return (34, 34, 34) if clear > 0.05 and lum and sum(lum) / len(lum) > 200 else (255, 255, 255)


def to_jpeg(im: Image.Image, width: int) -> bytes:
    flat = Image.new("RGB", im.size, _backdrop(im))
    flat.paste(im, mask=im.getchannel("A"))
    if flat.width > width:
        flat = flat.resize((width, round(flat.height * width / flat.width)), Image.LANCZOS)
    out = io.BytesIO()
    flat.save(out, "JPEG", quality=82, optimize=True, progressive=True)
    return out.getvalue()


# --- one club --------------------------------------------------------------------------------------------------------

def collect(card: dict, taken: set[str]) -> tuple[list[dict], dict]:
    """(photos best first, logo) as [{jpeg, page, src}], {jpeg, page, src} or {}. `taken`: image URLs already used by
    another club (a shared image is a site banner, not this club's)."""
    deadline = time.time() + CLUB_BUDGET_S
    left = lambda: min(TIMEOUT, deadline - time.time())  # noqa: E731
    queue, pages, cands = pages_for(card), [], []
    while queue and len(pages) < MAX_PAGES and left() > 0.5:
        url = queue.pop(0)
        if url in pages:
            continue
        try:
            body, ctype, final = fetch(url, HTML_CAP, "text/html,application/xhtml+xml", left())
        except Exception:  # noqa: BLE001
            continue
        pages.append(url)
        if "html" not in ctype:
            continue
        page = read_page(body.decode("utf-8", "replace"), final)
        cands += page.cands
        if len(pages) == 1:  # the club's homepage: follow its gallery / events / about links next
            queue = subpages(page, final, MAX_PAGES - 1) + queue

    seen, ordered = set(), []
    for c in cands:
        if c.url not in seen and c.url not in taken and not _skip_image(c.url):
            seen.add(c.url)
            ordered.append(c)
    photo_cands = [c for c in ordered if c.kind in ("og", "twitter", "img", "bg")
                   and not NOT_PHOTO.search(c.hint + " " + urlparse(c.url).path)]  # path too: .../avatars/x.jpg
    tokens = _name_tokens(card.get("name", ""))
    logo_cands = ([c for c in ordered if c.kind == "img" and LOGO_HINT.search(c.hint) and not OTHER_ORG.search(c.hint)
                   and (c.in_header or any(t in re.sub(r"[^a-z0-9]", "", c.hint.lower()) for t in tokens))]
                  + sorted((c for c in ordered if c.kind == "icon" and (c.size >= LOGO_MIN_SIDE or not c.size)),
                           key=lambda c: -c.size))

    photos, logo, og_logo, tries = [], {}, None, {"photo": 0, "logo": 0}

    def get(c: Cand, kind: str = "photo") -> Pic | None:
        if tries[kind] >= (MAX_DOWNLOADS if kind == "photo" else MAX_LOGO_DOWNLOADS) or left() <= 0.5:
            return None
        tries[kind] += 1
        try:
            data, itype, _ = fetch(sized(c.url), IMAGE_CAP, "image/jpeg,image/png,image/webp,image/gif", left())
            return decode(data) if itype in IMAGE_TYPES else None
        except Exception:  # noqa: BLE001
            return None

    for c in photo_cands:
        p = get(c)
        if not p:
            continue
        if is_photo(p):
            if any(p.sha == q["pic"].sha or _near(p.dhash, q["pic"].dhash) for q in photos):
                continue
            w, h = p.im.size
            score = min(w * h, 1_000_000) / 1_000_000 + (0.6 if GOOD_HINT.search(c.hint) else 0) \
                + (0.2 if c.kind == "og" else 0)
            photos.append({"pic": p, "page": c.page, "src": c.url, "score": score})
        elif c.kind in ("og", "twitter") and og_logo is None and is_logo(p) and p.colors < LOGO_MAX_COLORS:
            og_logo = {"pic": p, "page": c.page, "src": c.url}  # a logo-like og:image: a fallback logo
    for c in logo_cands:
        if logo:
            break
        p = get(c, "logo")
        named = any(t in re.sub(r"[^a-z0-9]", "", c.hint.lower()) for t in tokens)
        if p and is_logo(p) and (c.kind == "icon" or p.colors < (LOGO_MAX_COLORS_NAMED if named else LOGO_MAX_COLORS)):
            logo = {"pic": p, "page": c.page, "src": c.url}
    if not logo and og_logo:
        logo = og_logo
    if logo:
        photos = [q for q in photos if not _near(q["pic"].dhash, logo["pic"].dhash)]
    photos = sorted(photos, key=lambda q: -q["score"])[:MAX_PHOTOS]
    out = [{"jpeg": to_jpeg(q["pic"].im, PHOTO_WIDTH), "page": q["page"], "src": q["src"]} for q in photos]
    return out, ({"jpeg": to_jpeg(logo["pic"].im, LOGO_WIDTH), "page": logo["page"], "src": logo["src"]}
                 if logo else {})


# --- storage -----------------------------------------------------------------------------------------------------------

def _db() -> sqlite3.Connection:
    CATALOG_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(CATALOG_DB, timeout=10)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con


def url_for(file: str) -> str:
    return f"/api/images/{file}" if file else ""


def _store(campus: str, key: str, item: dict) -> dict:
    data = item["jpeg"]
    file = f"{campus}-{key}-{hashlib.sha256(data).hexdigest()[:8]}.jpg"  # content hash: safe to cache forever
    IMAGES.mkdir(parents=True, exist_ok=True)
    if not (IMAGES / file).exists():
        tmp = IMAGES / (file + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(IMAGES / file)
    return {"file": file, "page": item["page"], "src": item["src"]}


def lookup(campus: str, names: list[str]) -> dict[str, dict]:
    """normalized name -> {"photos": [url, ...], "logo": url} for clubs with any media."""
    keys = list({norm(n) for n in names if n})
    if not keys:
        return {}
    with closing(_db()) as con:
        rows = con.execute(f"SELECT key, photos, logo FROM club_media WHERE campus = ? AND key IN "
                           f"({','.join('?' * len(keys))})", (campus, *keys)).fetchall()
    out = {}
    for k, photos, logo in rows:
        photos, logo = json.loads(photos), json.loads(logo)
        if photos or logo:
            out[k] = {"photos": [url_for(p["file"]) for p in photos], "logo": url_for(logo.get("file", ""))}
    return out


def _lock_for(campus: str, key: str) -> threading.Lock:
    with _locks_lock:
        return _key_locks.setdefault((campus, key), threading.Lock())


def ensure(campus: str, card: dict, refetch: bool = False) -> dict:
    """The club's media ({"photos": [...], "logo": ...} as stored), fetched once. Clubs where nothing was found are
    retried after CATALOG_MAX_AGE_DAYS."""
    key = norm(card.get("name", ""))
    if not key:
        return {"photos": [], "logo": {}}
    with _lock_for(campus, key):
        with closing(_db()) as con:
            row = con.execute("SELECT photos, logo, fetched_at FROM club_media WHERE campus = ? AND key = ?",
                              (campus, key)).fetchone()
            if row and not refetch:
                photos, logo = json.loads(row[0]), json.loads(row[1])
                if photos or logo or time.time() - row[2] < CATALOG_MAX_AGE_DAYS * 86400:
                    return {"photos": photos, "logo": logo}
            taken = set()
            for p, lg in con.execute("SELECT photos, logo FROM club_media WHERE NOT (campus = ? AND key = ?)",
                                     (campus, key)):
                taken |= {x["src"] for x in json.loads(p)} | ({json.loads(lg)["src"]} if json.loads(lg) else set())
            # Hashes of other clubs' stored images: the same image on two clubs is a template, not either club's.
            shared = set()
            for p, lg in con.execute("SELECT photos, logo FROM club_media WHERE NOT (campus = ? AND key = ?)",
                                     (campus, key)):
                shared |= {x["file"][-12:-4] for x in json.loads(p)}
                if json.loads(lg):
                    shared.add(json.loads(lg)["file"][-12:-4])
        with _slots:
            found_photos, found_logo = collect(card, taken)
        sha8 = lambda item: hashlib.sha256(item["jpeg"]).hexdigest()[:8]  # noqa: E731 - matches _store's file name
        found_photos = [p for p in found_photos if sha8(p) not in shared]
        if found_logo and sha8(found_logo) in shared:
            found_logo = {}
        photos = [_store(campus, key, p) for p in found_photos]
        logo = _store(campus, key, found_logo) if found_logo else {}
        with closing(_db()) as con, con:
            con.execute("INSERT OR REPLACE INTO club_media VALUES (?,?,?,?,?)",
                        (campus, key, json.dumps(photos), json.dumps(logo), time.time()))
        return {"photos": photos, "logo": logo}


def ensure_async(campus: str, card: dict) -> None:
    def run():
        try:
            ensure(campus, card)
        except Exception:  # noqa: BLE001 - missing photos must never affect research
            traceback.print_exc()
    threading.Thread(target=run, daemon=True).start()


# --- commands ------------------------------------------------------------------------------------------------------------

def _all_clubs(job_ids: list[str]) -> list[tuple[str, dict]]:
    from .catalog import _db as catalog_db  # noqa: PLC0415
    from .jobs import job_files, read_job  # noqa: PLC0415
    with closing(catalog_db()) as con:
        clubs = [(campus, json.loads(card)) for campus, card in con.execute("SELECT campus, card FROM clubs")]
    for p in ([JOBS / f"{j}.json" for j in job_ids] if job_ids else job_files()):
        job = read_job(p)
        if not job:
            print(f"skipped {p.name}: not a readable job file")
            continue
        clubs += [(job["profile"].get("campus") or "seattle", c) for c in job["cards"]]
    seen, out = set(), []
    for campus, card in clubs:
        if norm(card["name"]) and (campus, norm(card["name"])) not in seen:
            seen.add((campus, norm(card["name"])))
            out.append((campus, card))
    return out


def backfill(job_ids: list[str], refetch: bool = False) -> None:
    """Fetch media for every catalog club and every card in the given jobs (default: all jobs)."""
    def one(item):
        campus, card = item
        try:
            m = ensure(campus, card, refetch)
            return f"{len(m['photos'])} photos, {'logo' if m['logo'] else 'no logo'}  {card['name'][:50]}"
        except Exception as e:  # noqa: BLE001
            return f"error {type(e).__name__}: {e}  {card['name'][:50]}"
    with ThreadPoolExecutor(3) as ex:
        for line in ex.map(one, _all_clubs(job_ids)):
            print(line, flush=True)


def _rows(name_filter: str) -> list[tuple]:
    with closing(_db()) as con:
        rows = con.execute("SELECT campus, key, photos, logo FROM club_media ORDER BY key").fetchall()
    return [(c, k, json.loads(p), json.loads(lg)) for c, k, p, lg in rows if name_filter.lower() in k]


def show(name_filter: str = "") -> None:
    for campus, key, photos, logo in _rows(name_filter):
        print(f"\n{campus}/{key}: {len(photos)} photos, {'logo' if logo else 'no logo'}")
        for p in photos:
            print(f"  photo {url_for(p['file'])}\n        from {p['src']}\n        on   {p['page']}")
        if logo:
            print(f"  logo  {url_for(logo['file'])}\n        from {logo['src']}\n        on   {logo['page']}")


def sheet(out: str, name_filter: str = "") -> None:
    """One row per club: logo (small, left) then its photos."""
    from PIL import ImageDraw  # noqa: PLC0415
    rows = [r for r in _rows(name_filter) if r[2] or r[3]]
    cell = 180
    img = Image.new("RGB", (cell * (MAX_PHOTOS + 1), (cell + 18) * max(1, len(rows))), "white")
    d = ImageDraw.Draw(img)
    for i, (_, key, photos, logo) in enumerate(rows):
        y = i * (cell + 18)
        d.text((4, y + 2), key[:60], fill="black")
        for j, item in enumerate(([logo] if logo else [{}]) + photos):
            if item and (IMAGES / item["file"]).exists():
                with Image.open(IMAGES / item["file"]) as im:
                    im.thumbnail((cell - 8, cell - 8) if j else (cell // 2, cell // 2))
                    img.paste(im, (j * cell + 4, y + 16))
    img.save(out, quality=85)
    print(f"wrote {out} ({len(rows)} clubs)")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["backfill"]:
        backfill([a for a in args[1:] if a != "--refetch"], refetch="--refetch" in args)
    elif args[:1] == ["show"]:
        show(" ".join(args[1:]))
    elif args[:1] == ["sheet"] and len(args) >= 2:
        sheet(args[1], " ".join(args[2:]))
    else:
        print(__doc__)
