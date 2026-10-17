from pydantic import BaseModel, Field


# ---- What the model returns during ingest -------------------------------------------

class DraftSubstep(BaseModel):
    text: str = Field(description="One concrete action, e.g. 'Sift the flour into the batter'")
    start: float | None = Field(None, description="Start time in seconds, if from a video")
    end: float | None = Field(None, description="End time in seconds, if from a video")


class DraftStep(BaseModel):
    title: str = Field(description="Short imperative title, max 6 words")
    start: float | None = Field(None, description="Start time in seconds of the whole step")
    end: float | None = Field(None, description="End time in seconds of the whole step")
    substeps: list[DraftSubstep] = Field(default_factory=list)
    visual_check: str = Field(description=(
        "The observable END STATE that proves the step is done, as a webcam pointed at the "
        "workspace would see it. Mention objects, positions, colors, textures. Never quantities or time."))
    verifiable: bool = Field(description="False if the step cannot be seen on camera (preheat, wait, off-camera)")
    timer_seconds: int | None = Field(None, description="Set when the step is mostly waiting")


class DraftPlan(BaseModel):
    title: str
    ingredients: list[str] = Field(default_factory=list, description="Ingredients or materials, with amounts")
    steps: list[DraftStep]


# ---- What the app stores and serves --------------------------------------------------

class Substep(DraftSubstep):
    pass


class Step(DraftStep):
    index: int
    substeps: list[Substep] = Field(default_factory=list)


class Plan(BaseModel):
    id: str
    source_url: str
    kind: str  # "video" | "article"
    title: str
    ingredients: list[str] = Field(default_factory=list)
    video_url: str | None = None  # served by the backend
    duration: float | None = None
    steps: list[Step]


# ---- Live check ---------------------------------------------------------------------

class Frame(BaseModel):
    data_url: str  # data:image/jpeg;base64,...
    t_ms: int


class CheckRequest(BaseModel):
    plan_id: str
    step_index: int
    frames: list[Frame]


class CheckVerdict(BaseModel):
    done: bool = Field(description="True only if the end state is clearly visible in the latest frame")
    confidence: float = Field(description="0 to 1")
    hint: str = Field(description="One short friendly sentence on what is left; empty if done")


class CheckResult(CheckVerdict):
    step_index: int
    latency_ms: int
