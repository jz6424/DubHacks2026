import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import ingest, perceptron_api
from .config import MEDIA_DIR, PLANS_DIR
from .schemas import CheckRequest, CheckResult, Plan

app = FastAPI(title="Stepwise")


class IngestRequest(BaseModel):
    url: str
    force: bool = False


@app.post("/api/ingest")
def post_ingest(req: IngestRequest):
    job = ingest.start(req.url, req.force)
    return {"job_id": job.id, "stage": job.stage, "plan_id": job.plan_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = ingest.JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")
    return {"job_id": job.id, "stage": job.stage, "plan_id": job.plan_id, "error": job.error}


@app.get("/api/plans")
def list_plans():
    out = []
    for p in sorted(PLANS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        d = json.loads(p.read_text())
        out.append({"id": d["id"], "title": d["title"], "kind": d["kind"], "steps": len(d["steps"])})
    return out


def load_plan(pid: str) -> Plan:
    p = PLANS_DIR / f"{pid}.json"
    if not p.exists():
        raise HTTPException(404, "Unknown plan")
    return Plan.model_validate_json(p.read_text())


@app.get("/api/plans/{pid}")
def get_plan(pid: str) -> Plan:
    return load_plan(pid)


@app.get("/api/media/{name}")
def media(name: str):
    path = (MEDIA_DIR / name).resolve()
    if path.parent != MEDIA_DIR.resolve() or not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="video/mp4")


@app.post("/api/check")
def check(req: CheckRequest) -> CheckResult:
    plan = load_plan(req.plan_id)
    if not 0 <= req.step_index < len(plan.steps):
        raise HTTPException(400, "Bad step index")
    if not req.frames:
        raise HTTPException(400, "No frames")
    step = plan.steps[req.step_index]
    verdict, latency = perceptron_api.check_step(req.frames[-4:], step)
    return CheckResult(**verdict.model_dump(), step_index=req.step_index, latency_ms=latency)
