"""HuskyMatch API."""
from typing import Literal

import anthropic
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from . import catalog, jobs, limits
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
    return {"clubs": catalog.stats(), "spend": limits.status()}


@app.post("/api/summary")
def summary(profile: Profile) -> dict:
    return {"summary": profile.summary(), "key": profile.key()}


def client_ip(request: Request) -> str:
    """The visitor's IP. X-Forwarded-For is only trusted from a proxy on this machine (Caddy), whose first address is
    the client; anything connecting directly is keyed on its own address, so the header can't be spoofed around."""
    peer = request.client.host if request.client else "unknown"
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd and peer in ("127.0.0.1", "::1"):
        return fwd.split(",")[0].strip() or peer
    return peer


@app.post("/api/jobs")
def start_job(profile: Profile, request: Request, fresh: bool = False) -> dict:
    try:
        return jobs.public(jobs.start(profile, force=fresh, ip=client_ip(request)))
    except limits.LimitHit as e:
        raise HTTPException(429, str(e))


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
    except limits.LimitHit as e:
        raise HTTPException(429, str(e))
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
