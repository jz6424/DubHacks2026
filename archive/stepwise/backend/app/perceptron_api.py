"""All calls to Perceptron Mk1.5 live here."""
import json
import logging
import time
from pathlib import Path

from perceptron import Client, perceive, pydantic_format, text, video, video_frames

from .config import CHECK_REASONING, INGEST_REASONING, MODEL
from .schemas import CheckVerdict, DraftPlan, Frame, Step

log = logging.getLogger("uvicorn.error")

PLAN_RULES = """Rules:
- Group the work into 5-8 major steps a person would check off; each should change what's on the
  workspace in a visible way. Put the detailed actions in substeps.
- Skip intros, outros, tasting and final presentation/beauty shots; they are not steps.
- Each step's start/end must cover all of its substeps. Times are in seconds from the start of the video.
- Read on-screen text overlays; they often contain the exact instructions and amounts.
- title: max 6 words, imperative, sentence case ("Whisk eggs and sugar").
- ingredients: EVERY ingredient/material with its amount, in normal sentence case ("70 g sugar (5 tbsp)").
- visual_check: one concrete sentence (10-20 words) describing the END STATE a webcam above the
  workspace would see once the step's core action is done: name the container, what's in it, and its
  color/texture/shape. Describe a result, not an action in progress or "after doing X". Never mention
  amounts, temperatures, durations, or presentation details.
- verifiable=false for steps a camera can't confirm (preheating, waiting, resting, off-camera work).
- timer_seconds only when the step is mostly waiting."""


def _upload(path: Path) -> str:
    with Client() as c:
        return c.files.upload(path, purpose="vision").id


def plan_from_video(path: Path, given_steps: list[str], context: str) -> DraftPlan:
    file_id = _upload(path)
    if given_steps:
        ask = ("The tutorial's own steps are listed below. Keep them (merge trivial ones), "
               "and find where each happens in the video.\n" + "\n".join(f"- {s}" for s in given_steps))
    else:
        ask = "Work out the steps the person performs in this video."
    if context:
        ask += f"\n\nExtra context from the page/description (may contain ingredients):\n{context[:4000]}"

    @perceive(model=MODEL, reasoning_effort=INGEST_REASONING, max_tokens=8192,
              response_format=pydantic_format(DraftPlan))
    def run():
        return video(file_id=file_id) + text(
            f"This is a DIY/cooking tutorial. Give the ingredients/materials and a step-by-step plan "
            f"with timestamps.\n{ask}\n\n{PLAN_RULES}")

    return DraftPlan.model_validate(json.loads(run().text))


def plan_from_text(title: str, body: str, given_steps: list[str]) -> DraftPlan:
    source = "\n".join(f"- {s}" for s in given_steps) if given_steps else body[:12000]

    @perceive(model=MODEL, reasoning_effort=INGEST_REASONING, max_tokens=8192,
              response_format=pydantic_format(DraftPlan))
    def run():
        return text(f"Tutorial: {title}\n\n{source}\n\nTurn this into a step-by-step plan. "
                    f"There is no video, so leave all start/end times null.\n\n{PLAN_RULES}")

    return DraftPlan.model_validate(json.loads(run().text))


CHECK_PROMPT = """These are the last few webcam frames (oldest first) of someone doing a DIY step.
Step: "{title}"
The step is complete when: {check}
Judge the MOST RECENT frame. done=true only if that end state is clearly visible.
Hands partially covering the work is fine; if the work isn't visible at all, done=false with low confidence.
hint: one short, friendly sentence about what's left (empty if done)."""


def check_step(frames: list[Frame], step: Step) -> tuple[CheckVerdict, int]:
    @perceive(model=MODEL, reasoning_effort=CHECK_REASONING, max_tokens=1024,
              response_format=pydantic_format(CheckVerdict))
    def run():
        media = (video_frames([(f.data_url, f.t_ms) for f in frames]) if len(frames) >= 2
                 else _image(frames[0].data_url))
        return media + text(CHECK_PROMPT.format(title=step.title, check=step.visual_check))

    t0 = time.perf_counter()
    res = run()
    ms = int((time.perf_counter() - t0) * 1000)
    log.info("check step=%s finish=%s usage=%s reasoning_chars=%s ms=%s", step.index, res.finish_reason,
             res.usage, len(res.reasoning or ""), ms)
    return CheckVerdict.model_validate(json.loads(res.text)), ms


def _image(data_url: str):
    from perceptron import image
    return image(data_url)
