from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field


class SourceKind(str, Enum):
    youtube = "youtube"
    video_file = "video_file"
    article = "article"


class Step(BaseModel):
    index: int
    title: str                       # "Cream the butter and sugar"
    detail: str = ""                 # original instruction text
    video_start: float | None = None # seconds; None for article-only plans
    video_end: float | None = None
    visual_check: str = ""           # camera-verifiable end state, written at ingest
    verifiable: bool = True          # False -> timer / manual check-off
    timer_seconds: int | None = None # e.g. "bake 10 min"
    key_objects: list[str] = Field(default_factory=list)  # for grounding overlay


class Plan(BaseModel):
    id: str
    source_url: str
    kind: SourceKind
    title: str
    youtube_id: str | None = None
    duration: float | None = None
    steps: list[Step]


class CheckResult(BaseModel):
    step_index: int
    done: bool
    confidence: float                # 0..1
    hint: str = ""                   # "Bowl still has lumps — keep mixing"
    boxes: list[dict] = Field(default_factory=list)  # [{label, x1,y1,x2,y2}] normalized
    model: str = "isaac"
