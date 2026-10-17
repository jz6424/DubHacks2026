"""Crash Replay API."""
import re
import shutil
import time
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .pipeline.runner import is_running, start_background
from .pipeline.store import STAGES, Clip

app = FastAPI(title="Crash Replay")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])

ALLOWED_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}


def _get(clip_id: str) -> Clip:
    if not re.fullmatch(r"[a-z0-9_\-]{1,64}", clip_id):
        raise HTTPException(400, "bad clip id")
    clip = Clip(clip_id)
    if not clip.exists():
        raise HTTPException(404, "clip not found")
    return clip


def _summary(clip: Clip) -> dict:
    meta = clip.meta()
    st = clip.status()
    if st.get("state") == "running" and not is_running(clip):
        st["state"] = "interrupted"  # server restarted mid-run
    return {"id": clip.id, "title": meta.get("title", clip.id), "curated": meta.get("curated", False),
            "license": meta.get("license"), "source_url": meta.get("source_url"), "status": st,
            "ready": clip.has_stage("scene"), "stages": STAGES}


@app.get("/api/clips")
def list_clips() -> list[dict]:
    return [_summary(c) for c in Clip.all()]


@app.get("/api/clips/{clip_id}")
def get_clip(clip_id: str) -> dict:
    return _summary(_get(clip_id))


@app.get("/api/clips/{clip_id}/scene")
def get_scene(clip_id: str) -> dict:
    clip = _get(clip_id)
    scene = clip.stage("scene")
    if scene is None:
        raise HTTPException(409, "scene not ready")
    return scene


@app.get("/api/clips/{clip_id}/video")
def get_video(clip_id: str) -> FileResponse:
    clip = _get(clip_id)
    if not clip.video.exists():
        raise HTTPException(409, "video not ready")
    return FileResponse(clip.video, media_type="video/mp4")


@app.get("/api/clips/{clip_id}/frames/{index}")
def get_frame(clip_id: str, index: int) -> FileResponse:
    clip = _get(clip_id)
    path = clip.frames_dir / f"f_{index + 1:04d}.jpg"
    if not path.exists():
        raise HTTPException(404, "frame not found")
    return FileResponse(path, media_type="image/jpeg")


@app.post("/api/clips/{clip_id}/run")
def rerun(clip_id: str, from_stage: str | None = None) -> dict:
    clip = _get(clip_id)
    if from_stage and from_stage not in STAGES:
        raise HTTPException(400, f"unknown stage {from_stage}")
    start_background(clip, force_from=from_stage)
    return _summary(clip)


@app.post("/api/clips")
async def upload(file: UploadFile = File(...), title: str = Form("")) -> dict:
    ext = "." + (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else ""
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"unsupported file type {ext or '(none)'}")
    clip = Clip(f"up-{uuid.uuid4().hex[:10]}")
    clip.dir.mkdir(parents=True)
    with open(clip.dir / f"source{ext}", "wb") as out:
        shutil.copyfileobj(file.file, out)
    clip.write_meta({"id": clip.id, "title": title or file.filename or clip.id, "curated": False,
                     "license": "uploaded by user", "created": time.time()})
    start_background(clip)
    return _summary(clip)
