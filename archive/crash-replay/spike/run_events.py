"""(b) Overlay OCR, signal state, and first-contact clip queries."""
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from perceptron import image, perceive, pydantic_format, text, video_frames
from pydantic import BaseModel

from common import MODEL, extract_frames, timed


class Overlay(BaseModel):
    overlay_present: bool
    date: str | None
    time: str | None
    latitude: float | None
    longitude: float | None
    speed_value: float | None
    speed_unit: str | None


class Signal(BaseModel):
    signal_visible: bool
    facing_camera: bool | None
    state: Literal["red", "amber", "green", "red_amber", "off", "unknown", "none"]
    confidence: Literal["low", "medium", "high"]


def ask(img, prompt, fmt, effort="low"):
    @perceive(model=MODEL, reasoning_effort=effort, max_tokens=2048, response_format=pydantic_format(fmt))
    def f():
        return image(img) + text(prompt)
    return f()


OCR_PROMPT = ("Read the dashcam text overlay burned into this frame. Report date, time, GPS latitude/longitude and the "
              "vehicle speed with its unit exactly as shown. Use null for anything not shown.")
SIG_PROMPT = ("Is a traffic signal (traffic light) for vehicles on this road visible? If so, is its lit face toward the "
              "camera, and which lamp is lit? Say 'none' if no signal is visible and 'unknown' if you can't tell.")

jobs = []
for p, t in extract_frames("sb400", fps=1, start=0, end=18, width=1920):
    jobs.append((f"ocr_sb400_{t:06d}", str(p), OCR_PROMPT, Overlay))
for p, t in extract_frames("royalmail_cyclist", fps=2, start=36, end=40, width=1920):
    jobs.append((f"sig_royal_{t:06d}", str(p), SIG_PROMPT, Signal))
for p, t in extract_frames("tesla_kia", fps=0.25, start=0, end=20):
    jobs.append((f"sig_tesla_{t:06d}", str(p), SIG_PROMPT, Signal))
with ThreadPoolExecutor(3) as ex:
    list(ex.map(lambda j: timed(j[0], ask, j[1], j[2], j[3]), jobs))


def contact(clip, start, end, effort):
    fr = extract_frames(clip, fps=4, start=start, end=end)

    @perceive(model=MODEL, reasoning_effort=effort, max_tokens=8192, expects="clip")
    def f():
        return (video_frames([(str(p), t) for p, t in fr]) +
                text("Find the moment of first physical contact between two road vehicles (collision), and separately "
                     "the moment each involved vehicle comes to rest or leaves view. Return clips with a short label."))
    return timed(f"contact_{clip}_{effort}", f)


contact("tesla_kia", 10, 22, "low")
contact("sb400", 4, 17.5, "low")
contact("tesla_kia", 10, 22, "high")
