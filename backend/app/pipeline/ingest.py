"""Normalize the source to a browser-safe H.264 MP4 and extract analysis frames at FRAME_FPS."""
import json
import subprocess
from typing import Callable

import numpy as np

from ..config import FRAME_FPS, FRAME_WIDTH, MAX_CLIP_SECONDS
from .store import Clip


def _rate(r: str) -> float:
    num, den = r.split("/")
    return float(num) / float(den) if float(den) else 0.0


def probe(path) -> dict:
    """Display size (after any rotation flag, e.g. iPhone portrait/landscape), frame rates and duration."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,r_frame_rate,avg_frame_rate:stream_side_data=rotation:format=duration",
         "-of", "json", str(path)],
        check=True, capture_output=True, text=True).stdout
    d = json.loads(out)
    s, fmt = d["streams"][0], d.get("format", {})
    rot = next((int(sd.get("rotation", 0)) for sd in s.get("side_data_list", []) if "rotation" in sd), 0)
    w, h = int(s["width"]), int(s["height"])
    if abs(rot) % 180 == 90:
        w, h = h, w
    fps, avg = _rate(s["r_frame_rate"]), _rate(s.get("avg_frame_rate", "0/1"))
    return {"width": w, "height": h, "fps": fps, "avg_fps": avg, "rotation": rot,
            "variable_frame_rate": bool(avg) and abs(avg - fps) > 0.5,
            "duration": float(fmt.get("duration", 0.0))}


def detect_bars(src, duration: float, width: int, height: int) -> tuple[int, int, int, int] | None:
    """Find letterbox/pillarbox bars: edge columns/rows with no texture in any sampled frame (bars are flat colour or
    smooth gradients, unlike real picture). Returns an ffmpeg crop (w, h, x, y) or None."""
    frames = []
    for t in np.linspace(0.05, 0.95, 8) * max(duration, 0.1):
        raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1",
                              "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
        if len(raw) == width * height:
            frames.append(np.frombuffer(raw, np.uint8).reshape(height, width).astype(np.float32))
    if len(frames) < 4:
        return None
    F = np.stack(frames)
    col_tex = np.abs(np.diff(F, axis=2)).mean(axis=(0, 1))
    row_tex = np.abs(np.diff(F, axis=1)).mean(axis=(0, 2))

    def bounds(tex: np.ndarray, n: int) -> tuple[int, int]:
        live = np.nonzero(tex > 0.5)[0]
        if not len(live):
            return 0, n
        return int(live[0]), int(live[-1]) + 2

    x0, x1 = bounds(col_tex, width)
    y0, y1 = bounds(row_tex, height)
    if x0 < 0.03 * width and width - x1 < 0.03 * width and y0 < 0.03 * height and height - y1 < 0.03 * height:
        return None
    x0, y0 = x0 + 2, y0 + 2  # step inside any soft edge
    w, h = (x1 - x0 - 2) // 2 * 2, (y1 - y0 - 2) // 2 * 2
    return (w, h, x0, y0) if w > 0.3 * width and h > 0.3 * height else None


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

    progress(0.03, "checking for borders")
    filters = []
    crop = detect_bars(src, info["duration"], info["width"], info["height"])
    if crop:
        filters.append("crop={}:{}:{}:{}".format(*crop))
        notes.append(f"cropped borders: picture area {crop[0]}x{crop[1]} at ({crop[2]},{crop[3]})")
    if info["variable_frame_rate"]:
        # analysis converts frame numbers to time, so make the frame rate constant
        target = 30.0 if info["avg_fps"] > 30 or info["fps"] > 30 else round(info["fps"])
        filters.append(f"fps={target:g}")
        notes.append(f"variable frame rate ({info['avg_fps']:.1f} avg) resampled to a constant {target:g} fps")
    filters.append(f"scale='min({FRAME_WIDTH},iw)':-2")

    progress(0.05, "transcoding")
    tmp = clip.video.with_suffix(".tmp.mp4")
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-ss", str(start), "-i", str(src), "-t", str(end - start),
         "-vf", ",".join(filters), "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
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
        "crop": list(crop) if crop else None,
        "frame_fps": FRAME_FPS,
        "frames": [{"i": i, "t": round(i / FRAME_FPS, 3), "file": f.name} for i, f in enumerate(files)],
        "notes": notes,
        "summary": f"{len(files)} frames at {FRAME_FPS:g} fps, {v['width']}x{v['height']}, {v['duration']:.1f} s",
    }
