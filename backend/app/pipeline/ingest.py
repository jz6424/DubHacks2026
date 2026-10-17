"""Normalize the source to a browser-safe H.264 MP4 and extract analysis frames at FRAME_FPS."""
import json
import subprocess
from typing import Callable

from ..config import FRAME_FPS, FRAME_WIDTH, MAX_CLIP_SECONDS
from .store import Clip


def probe(path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,r_frame_rate:format=duration", "-of", "json", str(path)],
        check=True, capture_output=True, text=True).stdout
    d = json.loads(out)
    s, fmt = d["streams"][0], d.get("format", {})
    num, den = s["r_frame_rate"].split("/")
    return {"width": int(s["width"]), "height": int(s["height"]), "fps": float(num) / float(den),
            "duration": float(fmt.get("duration", 0.0))}


def run(clip: Clip, progress: Callable[[float, str], None]) -> dict:
    src = clip.source()
    info = probe(src)
    meta = clip.meta()
    start = float(meta.get("trim_start", 0.0))
    end = float(meta.get("trim_end", info["duration"]))
    end = min(end, start + MAX_CLIP_SECONDS, info["duration"] or end)
    notes = []
    if info["duration"] and info["duration"] - start > MAX_CLIP_SECONDS:
        notes.append(f"clip trimmed to {MAX_CLIP_SECONDS:.0f} s")

    progress(0.05, "transcoding")
    tmp = clip.video.with_suffix(".tmp.mp4")
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-ss", str(start), "-i", str(src), "-t", str(end - start),
         "-vf", f"scale='min({FRAME_WIDTH},iw)':-2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(tmp)],
        check=True)
    tmp.replace(clip.video)

    progress(0.6, "extracting frames")
    clip.frames_dir.mkdir(parents=True, exist_ok=True)
    for old in clip.frames_dir.glob("f_*.jpg"):
        old.unlink()
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-i", str(clip.video), "-vf", f"fps={FRAME_FPS}", "-q:v", "3",
         str(clip.frames_dir / "f_%04d.jpg")],
        check=True)
    files = sorted(clip.frames_dir.glob("f_*.jpg"))
    v = probe(clip.video)
    return {
        "video": {"width": v["width"], "height": v["height"], "fps": v["fps"], "duration": v["duration"]},
        "source": info,
        "trim": [start, end],
        "frame_fps": FRAME_FPS,
        "frames": [{"i": i, "t": round(i / FRAME_FPS, 3), "file": f.name} for i, f in enumerate(files)],
        "notes": notes,
        "summary": f"{len(files)} frames at {FRAME_FPS:g} fps, {v['width']}x{v['height']}, {v['duration']:.1f} s",
    }
