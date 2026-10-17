"""Perceptron Mk1.5 calls: bounded concurrency, retry on rate limits / transient errors, and an on-disk cache.

Every call is cached as JSON under the clip's cache dir, keyed by the caller, so re-running a stage is free and demos
replay without network access.
"""
import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

from perceptron import detect, image, perceive, pydantic_format, text
from pydantic import BaseModel

from .config import DETECT_CLASSES, MODEL, MODEL_CONCURRENCY

_slots = threading.BoundedSemaphore(MODEL_CONCURRENCY)
_RETRYABLE = ("rate limit", "1015", "timeout", "temporarily", "502", "503", "504", "500")


def _usage(res: Any) -> dict | None:
    u = getattr(res, "usage", None)
    if u is None:
        return None
    if isinstance(u, dict):
        return u
    return getattr(u, "model_dump", lambda: dict(u.__dict__))()


def _box(b: Any) -> dict:
    return {"x0": b.top_left.x, "y0": b.top_left.y, "x1": b.bottom_right.x, "y1": b.bottom_right.y,
            "label": b.mention}


def cached_call(cache_file: Path, fn: Callable[[], Any], to_record: Callable[[Any], dict]) -> dict:
    """Return the cached record if present, otherwise run fn with retries and cache to_record(result)."""
    if cache_file.exists():
        return json.loads(cache_file.read_text())
    last: Exception | None = None
    for attempt in range(6):
        with _slots:
            t0 = time.time()
            try:
                res = fn()
            except Exception as e:  # noqa: BLE001 - SDK raises several error types; retry only the transient ones
                last = e
                msg = str(e).lower()[:2000]
                if not any(k in msg for k in _RETRYABLE):
                    raise
            else:
                rec = {**to_record(res), "latency_s": round(time.time() - t0, 2), "usage": _usage(res),
                       "finish_reason": getattr(res, "finish_reason", None)}
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(rec))
                return rec
        time.sleep(2 * 2 ** attempt)
    raise RuntimeError(f"model call failed after retries: {last}")


def detect_frame(frame_path: Path, cache_file: Path, classes: list[str] | None = None) -> dict:
    """Boxes (normalized 0-1000) for road users in one frame. Reasoning off: the spike showed it isn't needed here."""
    return cached_call(
        cache_file,
        lambda: detect(image(str(frame_path)), classes=classes or DETECT_CLASSES, model=MODEL, reasoning_effort="none",
                       max_tokens=4096),
        lambda r: {"boxes": [_box(b) for b in (r.boxes or [])], "text": r.text},
    )


def ask_structured(frame_path: Path, prompt: str, schema: type[BaseModel], cache_file: Path,
                   effort: str = "low") -> dict:
    """Single-image question constrained to a pydantic schema. Returns {"data": {...} | None, ...}."""
    @perceive(model=MODEL, reasoning_effort=effort, max_tokens=2048, response_format=pydantic_format(schema))
    def run():
        return image(str(frame_path)) + text(prompt)

    def record(r: Any) -> dict:
        try:
            data = schema.model_validate_json(r.text or "").model_dump()
        except Exception:  # noqa: BLE001 - empty/invalid output is recorded, not fatal
            data = None
        return {"data": data, "text": r.text}

    return cached_call(cache_file, run, record)
