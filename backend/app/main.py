"""HuskyMatch API."""
from typing import Literal

import anthropic
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import catalog, jobs
from .profile import BUDGET_LABEL, COMMITMENT_LABEL, GOALS, INTERESTS, Profile

app = FastAPI(title="HuskyMatch")


@app.get("/api/options")
def options() -> dict:
    """Quick-pick choices for onboarding (spec Phase 1), so the UI and the prompt agree on wording."""
    return {"interests": INTERESTS, "goals": GOALS, "commitment": COMMITMENT_LABEL, "budget": BUDGET_LABEL,
            "availability": ["weekday mornings", "weekday afternoons", "weekday evenings", "weekends"]}


@app.get("/api/catalog")
def catalog_stats() -> dict:
    """How many verified clubs are cached per campus."""
    return {"clubs": catalog.stats()}


@app.post("/api/summary")
def summary(profile: Profile) -> dict:
    return {"summary": profile.summary(), "key": profile.key()}


@app.post("/api/jobs")
def start_job(profile: Profile, fresh: bool = False) -> dict:
    return jobs.public(jobs.start(profile, force=fresh))


def _job(job_id: str) -> dict:
    job = jobs.load(job_id)
    if not job:
        raise HTTPException(404, "no such job")
    return job


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    return jobs.public(_job(job_id))


def _card(job: dict, club_id: str) -> None:
    if not any(c["club_id"] == club_id for c in job["cards"]):
        raise HTTPException(404, "no such club in this job")


def _call(fn, *args):
    try:
        return fn(*args)
    except anthropic.RateLimitError:
        raise HTTPException(429, "HuskyMatch is busy right now; try again in a minute.")
    except anthropic.APIStatusError as e:
        raise HTTPException(502, f"model error ({e.status_code})")
    except anthropic.APIConnectionError:
        raise HTTPException(502, "couldn't reach the model")


@app.post("/api/jobs/{job_id}/cards/{club_id}/more")
def more(job_id: str, club_id: str) -> dict:
    job = _job(job_id)
    _card(job, club_id)
    return _call(jobs.tell_more, job_id, club_id)


class Swipe(BaseModel):
    club_id: str
    action: Literal["right", "left", "super", "more"]


class SwipeSet(BaseModel):
    swipes: list[Swipe]


@app.post("/api/jobs/{job_id}/results")
def results(job_id: str, body: SwipeSet) -> dict:
    _job(job_id)
    return _call(jobs.results, job_id, [s.model_dump() for s in body.swipes])


@app.post("/api/jobs/{job_id}/cards/{club_id}/draft")
def draft(job_id: str, club_id: str) -> dict:
    job = _job(job_id)
    _card(job, club_id)
    return {"text": _call(jobs.draft, job_id, club_id)}
