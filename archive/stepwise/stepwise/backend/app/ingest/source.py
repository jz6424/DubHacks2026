"""Step 1 of ingest: figure out what the URL is and pull raw material."""
import json, re, subprocess
from dataclasses import dataclass, field
from pathlib import Path

MEDIA = Path(__file__).resolve().parents[3] / "data" / "media"
YT_RE = re.compile(r"(?:youtu\.be/|v=|shorts/)([\w-]{11})")


@dataclass
class RawSource:
    kind: str                          # youtube | article
    url: str
    title: str = ""
    text: str = ""                     # description / article body
    transcript: list[dict] = field(default_factory=list)  # [{start, dur, text}]
    video_path: Path | None = None
    youtube_id: str | None = None
    duration: float | None = None


def fetch(url: str) -> RawSource:
    if m := YT_RE.search(url):
        return _youtube(url, m.group(1))
    return _article(url)


def _youtube(url: str, vid: str) -> RawSource:
    MEDIA.mkdir(parents=True, exist_ok=True)
    out = MEDIA / f"{vid}.mp4"
    # 360p is plenty for Mk1 and keeps tokens/upload small
    subprocess.run(["yt-dlp", "-f", "worse[height>=360][ext=mp4]/worst[ext=mp4]",
                    "-o", str(out), "--write-info-json", url], check=True)
    info = json.loads(out.with_suffix(".info.json").read_text())
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        transcript = YouTubeTranscriptApi().fetch(vid).to_raw_data()
    except Exception:
        transcript = []                # fine: Mk1 can still segment from visuals
    return RawSource("youtube", url, info.get("title", ""), info.get("description", ""),
                     transcript, out, vid, info.get("duration"))


def _article(url: str) -> RawSource:
    import trafilatura
    html = trafilatura.fetch_url(url)
    # TODO: prefer schema.org Recipe JSON-LD (recipeInstructions) when present — free, exact steps
    text = trafilatura.extract(html, include_formatting=True) or ""
    # TODO: if article embeds a YouTube video, also run _youtube() and merge
    return RawSource("article", url, title=_title(html), text=text)


def _title(html: str) -> str:
    m = re.search(r"<title>(.*?)</title>", html or "", re.S)
    return m.group(1).strip() if m else "Untitled"

