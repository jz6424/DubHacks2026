"""Crash Replay API."""
import re
import shutil
import time
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .pipeline.runner import IDENTITY_STAGES, is_running, start_background
from .pipeline.store import STAGES, Clip
from .pipeline.track import TIERS, load_overrides

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


class Overrides(BaseModel):
    merge: list[list[str]] = Field(default_factory=list)  # [keep, absorb]: same physical vehicle
    tier: dict[str, str] = Field(default_factory=dict)  # id -> involved | nearby | background | hidden
    labels: dict[str, str] = Field(default_factory=dict)
    rejected_links: list[list[str]] = Field(default_factory=list)  # suggestions the user dismissed


@app.get("/api/clips/{clip_id}/overrides")
def get_overrides(clip_id: str) -> dict:
    ov = load_overrides(_get(clip_id))
    ov.setdefault("rejected_links", [])
    return ov


@app.put("/api/clips/{clip_id}/overrides")
def put_overrides(clip_id: str, ov: Overrides) -> dict:
    """Save the user's corrections and recompute only what depends on identity (tracks, positions, suggestions)."""
    clip = _get(clip_id)
    if is_running(clip):
        raise HTTPException(409, "clip is being processed; try again when it finishes")
    ident = re.compile(r"[A-Z]\d{1,4}")
    for pair in ov.merge + ov.rejected_links:
        if len(pair) != 2 or not all(ident.fullmatch(x) for x in pair):
            raise HTTPException(400, f"bad id pair {pair}")
    bad = {k: v for k, v in ov.tier.items() if v not in TIERS or not ident.fullmatch(k)}
    if bad:
        raise HTTPException(400, f"bad tiers {bad}")
    data = ov.model_dump()
    # remember where each mentioned track starts, so corrections survive renumbering if tracking changes
    current = (clip.stage("track") or {}).get("sigs", {})
    ids = {x for pair in ov.merge + ov.rejected_links for x in pair} | set(ov.tier) | set(ov.labels)
    old_sigs = load_overrides(clip).get("sigs", {})
    data["sigs"] = {i: current.get(i) or old_sigs.get(i) for i in ids}
    data["sigs"] = {k: v for k, v in data["sigs"].items() if v}
    clip._write(clip.dir / "overrides.json", data)
    start_background(clip, rerun=IDENTITY_STAGES)
    return _summary(clip)


@app.get("/api/clips/{clip_id}/crop/{index}")
def get_crop(clip_id: str, index: int, box: str, w: int = 160) -> Response:
    """A padded crop of one analysis frame around a box, with any licence plates in it pixelated."""
    import cv2

    clip = _get(clip_id)
    path = clip.frames_dir / f"f_{index + 1:04d}.jpg"
    try:
        x0, y0, x1, y1 = (float(v) for v in box.split(","))
    except ValueError:
        raise HTTPException(400, "box must be x0,y0,x1,y1 in 0..1")
    if not path.exists() or not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise HTTPException(404, "no such frame or box")
    img = cv2.imread(str(path))
    H, W = img.shape[:2]
    for p in (clip.stage("plates") or {}).get("plates", []):
        if p["i"] == index:
            a, b, c, d = p["box"]
            px0, py0, px1, py1 = int(a * W), int(b * H), int(c * W) + 1, int(d * H) + 1
            region = img[py0:py1, px0:px1]
            if region.size:
                small = cv2.resize(region, (6, 3), interpolation=cv2.INTER_AREA)
                img[py0:py1, px0:px1] = cv2.resize(small, (region.shape[1], region.shape[0]), interpolation=cv2.INTER_NEAREST)
    pw, ph = (x1 - x0) * 0.12, (y1 - y0) * 0.12
    crop = img[max(0, int((y0 - ph) * H)):int((y1 + ph) * H) + 1, max(0, int((x0 - pw) * W)):int((x1 + pw) * W) + 1]
    w = max(48, min(w, 480))
    crop = cv2.resize(crop, (w, max(1, int(crop.shape[0] * w / max(crop.shape[1], 1)))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return Response(buf.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})
