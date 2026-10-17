"""Step 3: timestamp steps against the video with Mk1.

Two modes:
  ALIGN    – steps known (from description/article) -> find [start,end] for each
  DISCOVER – no steps -> Mk1 segments the video into steps itself

Long videos: cut into ~150 s chunks with 10 s overlap (Mk1 context ~32k on
OpenRouter), downscale to 360p / 1 fps, run chunks in parallel, then merge.
"""
import subprocess, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from ..perceptron import mk1_video

CHUNK, OVERLAP = 150, 10

SEG_SCHEMA = {"type": "object", "properties": {"segments": {"type": "array", "items": {
    "type": "object", "properties": {
        "step": {"type": "string"},          # step text (DISCOVER) or index as string (ALIGN)
        "start": {"type": "number"}, "end": {"type": "number"}},
    "required": ["step", "start", "end"]}}}, "required": ["segments"]}


def chunk_video(path: Path, duration: float) -> list[tuple[float, bytes]]:
    chunks, t = [], 0.0
    while t < duration:
        with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
            subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-t", str(CHUNK + OVERLAP), "-i", str(path),
                            "-vf", "scale=-2:360,fps=1", "-an", f.name], check=True, capture_output=True)
            chunks.append((t, Path(f.name).read_bytes()))
        t += CHUNK
    return chunks


def align(video: Path, duration: float, steps: list[str] | None,
          transcript: list[dict]) -> list[dict]:
    chunks = chunk_video(video, duration)

    def run(chunk):
        offset, data = chunk
        tx = _transcript_window(transcript, offset, offset + CHUNK + OVERLAP)
        if steps:
            listed = "\n".join(f"{i}. {s}" for i, s in enumerate(steps))
            prompt = (f"This clip starts at {offset:.0f}s of a tutorial. Steps:\n{listed}\n"
                      f"Transcript for this clip:\n{tx}\n"
                      "For each step actually performed on screen in this clip, return its index "
                      "as `step` and the clip-relative start/end seconds. Omit steps not shown.")
        else:
            prompt = (f"This clip starts at {offset:.0f}s of a DIY/cooking tutorial. Transcript:\n{tx}\n"
                      "Segment it into the distinct physical steps the person performs. For each, "
                      "give a short imperative `step` and clip-relative start/end seconds.")
        segs = mk1_video(data, prompt, SEG_SCHEMA)["segments"]
        return [{**s, "start": s["start"] + offset, "end": s["end"] + offset} for s in segs]

    with ThreadPoolExecutor(4) as ex:
        segs = [s for part in ex.map(run, chunks) for s in part]
    return merge(segs, steps)


def merge(segs: list[dict], steps: list[str] | None) -> list[dict]:
    """
    ALIGN:    group by step index; start=min(start), end=max(end); enforce monotonic
              order (if step i+1 starts before step i, clamp); steps never found get
              interpolated between neighbours and flagged low-confidence.
    DISCOVER: sort by start; merge adjacent segments in the overlap window whose text
              is near-duplicate (same step seen by two chunks); drop segments < 3 s.
    """
    ...  # TODO


def _transcript_window(tx: list[dict], a: float, b: float) -> str:
    return " ".join(f"[{t['start']:.0f}] {t['text']}" for t in tx if a <= t["start"] < b)[:4000]
