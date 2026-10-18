"""Me&UDub API."""
from typing import Literal

import anthropic
import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import catalog, jobs, limits
from .config import IMAGES
from .profile import BUDGET_LABEL, COMMITMENT_LABEL, GOALS, INTERESTS, Profile

app = FastAPI(title="Me&UDub")


@app.get("/api/options")
def options() -> dict:
    """Quick-pick choices for onboarding (spec Phase 1), so the UI and the prompt agree on wording."""
    return {"interests": INTERESTS, "goals": GOALS, "commitment": COMMITMENT_LABEL, "budget": BUDGET_LABEL,
            "availability": ["weekday mornings", "weekday afternoons", "weekday evenings", "weekends"]}


@app.get("/api/catalog")
def catalog_stats() -> dict:
    """How many verified clubs are cached per campus."""
    return {"clubs": catalog.stats(), "spend": limits.status()}


@app.get("/api/catalog/search")
def catalog_search(q: str = "", campus: Literal["seattle", "bothell", "tacoma"] = "seattle", limit: int = 20) -> dict:
    """Search all catalog clubs by name, category or description; same card shape as jobs, neutral fit_reason."""
    return {"clubs": jobs.search_catalog(campus, q, max(1, min(limit, 50)))}


class FromCatalog(BaseModel):
    club_id: str


@app.post("/api/jobs/{job_id}/cards/from-catalog")
def card_from_catalog(job_id: str, body: FromCatalog) -> dict:
    """Add a searched catalog club to this job's deck (no model calls), or return the card it already has."""
    _job(job_id)
    try:
        card = jobs.add_from_catalog(job_id, body.club_id)
    except jobs.TooManyAdded as e:
        raise HTTPException(429, str(e))
    if not card:
        raise HTTPException(404, "no such club in the catalog")
    return card


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
        raise HTTPException(429, "Me&UDub is busy right now; try again in a minute.")
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


@app.get("/api/images/{name}")
def image(name: str) -> FileResponse:
    """Club photos. Names carry a content hash, so they can be cached forever; always JPEGs we re-encoded ourselves."""
    if not re.fullmatch(r"[a-z]+-[a-z0-9]+-[0-9a-f]{8}\.jpg", name) or not (IMAGES / name).is_file():
        raise HTTPException(404, "no such image")
    return FileResponse(IMAGES / name, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=31536000, immutable",
                                 "X-Content-Type-Options": "nosniff"})
