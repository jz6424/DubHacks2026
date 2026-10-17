"""URL -> Plan. Cached by URL hash so the demo never waits on ingest."""
import hashlib, json
from pathlib import Path
from ..models import Plan, Step, SourceKind
from . import source, steps as steps_mod, align as align_mod, checks

PLANS = Path(__file__).resolve().parents[3] / "data" / "plans"


def ingest(url: str, progress=lambda stage, pct: None) -> Plan:
    pid = hashlib.sha1(url.encode()).hexdigest()[:10]
    cached = PLANS / f"{pid}.json"
    if cached.exists():
        return Plan.model_validate_json(cached.read_text())

    progress("fetching", 0.05)
    raw = source.fetch(url)

    progress("reading steps", 0.2)
    explicit = steps_mod.extract_steps(raw.title, raw.text)

    segments = []
    if raw.video_path:
        progress("watching video", 0.35)       # longest stage — UI should show chunk progress
        segments = align_mod.align(raw.video_path, raw.duration, explicit, raw.transcript)
        step_texts = explicit or [s["step"] for s in segments]
    else:
        step_texts = explicit or []
        # TODO: no explicit steps and no video -> split article paragraphs as fallback

    progress("writing checks", 0.85)
    enriched = checks.write_checks(raw.title, step_texts)

    plan = Plan(
        id=pid, source_url=url, kind=SourceKind(raw.kind), title=raw.title,
        youtube_id=raw.youtube_id, duration=raw.duration,
        steps=[Step(index=i, detail=step_texts[i],
                    video_start=segments[i]["start"] if i < len(segments) else None,
                    video_end=segments[i]["end"] if i < len(segments) else None,
                    **e) for i, e in enumerate(enriched)])
    cached.write_text(plan.model_dump_json(indent=2))
    progress("ready", 1.0)
    return plan
