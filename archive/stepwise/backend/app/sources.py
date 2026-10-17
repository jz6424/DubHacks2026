"""Turn a URL into raw material: a local video file and/or text with instructions."""
import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .config import MEDIA_DIR

VIDEO_HOSTS = re.compile(r"(youtube\.com|youtu\.be|vimeo\.com|tiktok\.com|instagram\.com)", re.I)
VIDEO_EXT = re.compile(r"\.(mp4|mov|webm)(\?|$)", re.I)
YT_EMBED = re.compile(r"(?:youtube\.com/embed/|youtube-nocookie\.com/embed/)([\w-]{11})")


@dataclass
class Source:
    url: str
    title: str = ""
    text: str = ""                       # description, article body, or recipe instructions
    given_steps: list[str] = field(default_factory=list)
    ingredients: list[str] = field(default_factory=list)
    video_path: Path | None = None
    duration: float | None = None

    @property
    def kind(self) -> str:
        return "video" if self.video_path else "article"


def url_id(url: str) -> str:
    return hashlib.sha1(url.strip().encode()).hexdigest()[:12]


def fetch(url: str) -> Source:
    if VIDEO_HOSTS.search(url):
        return _from_video_site(url)
    if VIDEO_EXT.search(url):
        return _from_direct_video(url)
    return _from_article(url)


def _from_video_site(url: str) -> Source:
    import yt_dlp

    out = MEDIA_DIR / f"{url_id(url)}.mp4"
    # YouTube rarely serves progressive (audio+video) files anymore, so merge
    # separate streams when ffmpeg is available; otherwise take video-only,
    # which is all the vision model needs.
    if shutil.which("ffmpeg"):
        fmt = ("bv*[ext=mp4][vcodec^=avc1][height<=480]+ba[ext=m4a]"
               "/bv*[ext=mp4][height<=480]+ba[ext=m4a]/b[ext=mp4][height<=480]"
               "/bv*[height<=480]+ba/b")
    else:
        fmt = ("b[ext=mp4][height<=480]/bv*[ext=mp4][vcodec^=avc1][height<=480]"
               "/bv*[ext=mp4][height<=480]/b[ext=mp4]/bv*[ext=mp4]")
    opts = {
        "format": fmt,
        "merge_output_format": "mp4",
        "outtmpl": str(out),
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=not out.exists())
    desc = info.get("description") or ""
    chapters = [c.get("title", "") for c in (info.get("chapters") or [])]
    return Source(url=url, title=info.get("title", ""), text=desc, given_steps=chapters,
                  video_path=out, duration=info.get("duration"))


def _from_direct_video(url: str) -> Source:
    out = MEDIA_DIR / f"{url_id(url)}.mp4"
    if not out.exists():
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
            r.raise_for_status()
            with out.open("wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
    name = url.rsplit("/", 1)[-1].split("?")[0]
    return Source(url=url, title=name, video_path=out)


def _from_article(url: str) -> Source:
    import trafilatura

    html = httpx.get(url, follow_redirects=True, timeout=30,
                     headers={"User-Agent": "Mozilla/5.0 (Stepwise)"}).text
    src = Source(url=url)
    _apply_recipe_jsonld(html, src)
    if not src.text:
        src.text = trafilatura.extract(html, include_formatting=True) or ""
    if not src.title:
        meta = trafilatura.extract_metadata(html)
        src.title = (meta.title if meta else "") or "Untitled"

    # An article that embeds a YouTube video: use the video for timestamps,
    # and the article's own steps as the step list.
    if m := YT_EMBED.search(html):
        try:
            vid = _from_video_site(f"https://www.youtube.com/watch?v={m.group(1)}")
            src.video_path, src.duration = vid.video_path, vid.duration
        except Exception:
            pass
    return src


def _apply_recipe_jsonld(html: str, src: Source) -> None:
    """Most recipe sites publish schema.org Recipe JSON-LD — exact steps for free."""
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for node in _walk(data):
            if not isinstance(node, dict):
                continue
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if "Recipe" not in types:
                continue
            src.title = node.get("name") or src.title
            src.ingredients = [str(i) for i in node.get("recipeIngredient") or []]
            src.given_steps = _instructions(node.get("recipeInstructions"))
            src.text = "\n".join(src.given_steps)
            return


def _walk(obj):
    if isinstance(obj, list):
        for x in obj:
            yield from _walk(x)
    elif isinstance(obj, dict):
        yield obj
        for k in ("@graph", "mainEntity"):
            if k in obj:
                yield from _walk(obj[k])


def _instructions(raw) -> list[str]:
    if isinstance(raw, str):
        return [s.strip() for s in re.split(r"\n+|(?<=\.)\s+(?=[A-Z])", raw) if s.strip()]
    steps: list[str] = []
    for item in raw or []:
        if isinstance(item, str):
            steps.append(item)
        elif isinstance(item, dict) and item.get("@type") == "HowToSection":
            steps += _instructions(item.get("itemListElement"))
        elif isinstance(item, dict):
            steps.append(item.get("text") or item.get("name") or "")
    return [re.sub(r"<[^>]+>", "", s).strip() for s in steps if s]
