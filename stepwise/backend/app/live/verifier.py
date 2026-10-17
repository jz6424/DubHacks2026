"""Turns a rolling buffer of webcam frames into CheckResults."""
import asyncio, time
from collections import deque
from ..models import Step, CheckResult
from ..perceptron import isaac_frames, mk1_video

SCHEMA = {"type": "object", "properties": {
    "done": {"type": "boolean"}, "confidence": {"type": "number"},
    "hint": {"type": "string"},
    "boxes": {"type": "array", "items": {"type": "object", "properties": {
        "label": {"type": "string"}, "x1": {"type": "number"}, "y1": {"type": "number"},
        "x2": {"type": "number"}, "y2": {"type": "number"}}}}},
    "required": ["done", "confidence", "hint"]}

PROMPT = """These are the last few webcam frames (oldest first) of someone doing: "{title}".
The step is complete when: {check}
Answer about the MOST RECENT frame. done=true only if the end state is clearly visible.
confidence 0..1. hint: one short, friendly sentence on what's left (empty if done).
Return boxes (normalized 0..1) around: {objects}."""


class Verifier:
    def __init__(self, interval=2.0, frames=4):
        self.buf: deque[bytes] = deque(maxlen=frames)
        self.interval = interval
        self.inflight = False

    def push(self, jpeg: bytes):
        self.buf.append(jpeg)

    async def check(self, step: Step) -> CheckResult | None:
        if self.inflight or len(self.buf) < 2:
            return None                 # drop rather than queue — freshness > completeness
        self.inflight = True
        try:
            out = await asyncio.to_thread(isaac_frames, list(self.buf), PROMPT.format(
                title=step.title, check=step.visual_check, objects=", ".join(step.key_objects)), SCHEMA)
            r = CheckResult(step_index=step.index, **out)
            # ambiguous zone -> escalate to Mk1 on a short clip (tie-breaker, rare)
            if 0.45 <= r.confidence < 0.7:
                r = await self.tiebreak(step) or r
            return r
        finally:
            self.inflight = False

    async def tiebreak(self, step: Step) -> CheckResult | None:
        """
        frames -> tiny mp4 via ffmpeg (or send frames as images if Mk1 accepts them)
        mk1_video(clip, same PROMPT, SCHEMA) -> CheckResult(model="mk1")
        Rate-limit: at most once per 10 s per step.
        """
        return None  # TODO
