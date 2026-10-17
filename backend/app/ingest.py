"""URL -> Plan, run as a background job so the UI can show progress."""
import threading
import traceback
import uuid
from dataclasses import dataclass, field

from . import perceptron_api, sources
from .config import PLANS_DIR
from .schemas import DraftPlan, Plan, Step, Substep


@dataclass
class Job:
    id: str
    url: str
    stage: str = "queued"
    plan_id: str | None = None
    error: str | None = None
    log: list[str] = field(default_factory=list)


JOBS: dict[str, Job] = {}


def start(url: str, force: bool = False) -> Job:
    job = Job(id=uuid.uuid4().hex[:8], url=url.strip())
    JOBS[job.id] = job
    pid = sources.url_id(job.url)
    if not force and (PLANS_DIR / f"{pid}.json").exists():
        job.stage, job.plan_id = "ready", pid
        return job
    threading.Thread(target=_run, args=(job,), daemon=True).start()
    return job


def _stage(job: Job, stage: str):
    job.stage = stage
    job.log.append(stage)


def _run(job: Job):
    try:
        _stage(job, "fetching")
        src = sources.fetch(job.url)
        pid = sources.url_id(job.url)

        if src.video_path:
            _stage(job, "watching")
            draft = perceptron_api.plan_from_video(src.video_path, src.given_steps, src.text)
        else:
            _stage(job, "reading")
            draft = perceptron_api.plan_from_text(src.title, src.text, src.given_steps)

        _stage(job, "finishing")
        plan = build_plan(pid, src, draft)
        (PLANS_DIR / f"{pid}.json").write_text(plan.model_dump_json(indent=2))
        job.plan_id = pid
        _stage(job, "ready")
    except Exception as e:  # surface to UI
        traceback.print_exc()
        job.error = f"{type(e).__name__}: {e}"
        _stage(job, "error")


def build_plan(pid: str, src: sources.Source, draft: DraftPlan) -> Plan:
    steps = [Step(index=i, **s.model_dump(exclude={"substeps"}),
                  substeps=[Substep(**ss.model_dump()) for ss in s.substeps])
             for i, s in enumerate(draft.steps)]
    if src.video_path:
        _clean_times(steps, src.duration)
    return Plan(
        id=pid, source_url=src.url, kind=src.kind,
        title=draft.title or src.title,
        ingredients=src.ingredients or draft.ingredients,
        video_url=f"/api/media/{pid}.mp4" if src.video_path else None,
        duration=src.duration, steps=steps)


def _clean_times(steps: list[Step], duration: float | None):
    """Make segments usable for looping: fill gaps, enforce order, pad slightly."""
    MIN_LEN = 6.0
    all_times: list[float] = []
    for s in steps:  # derive step bounds from substeps when missing
        times = [t for ss in s.substeps for t in (ss.start, ss.end) if t is not None]
        if s.start is None and times:
            s.start = min(times)
        if s.end is None and times:
            s.end = max(times)
        all_times += times + [t for t in (s.start, s.end) if t is not None]
    end_cap = duration or (max(all_times, default=0) + 5)
    prev = 0.0
    for i, s in enumerate(steps):
        s.start = max(0.0, s.start if s.start is not None else prev)
        if s.end is None or s.end <= s.start:
            fallback = end_cap if i == len(steps) - 1 else s.start + 15
            s.end = next((x.start for x in steps[i + 1:] if x.start is not None and x.start > s.start), fallback)
        if s.end - s.start < MIN_LEN:
            s.end = min(end_cap, s.start + MIN_LEN)
        for j, ss in enumerate(s.substeps):  # open-ended substeps run until the next one (or step end)
            if ss.start is not None and (ss.end is None or ss.end <= ss.start):
                ss.end = next((x.start for x in s.substeps[j + 1:]
                               if x.start is not None and x.start > ss.start), s.end)
                if ss.end <= ss.start:
                    ss.end = ss.start + 4
                s.end = max(s.end, ss.end)
        prev = s.end
        s.start = max(0.0, s.start - 1.0)   # 1 s lead-in / tail so loops don't clip the action
        s.end = min(end_cap, s.end + 1.0)
