import asyncio, json
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()
from .ingest.pipeline import ingest, PLANS          # noqa: E402
from .live.tracker import Tracker                    # noqa: E402
from .live.verifier import Verifier                  # noqa: E402
from .models import Plan                             # noqa: E402

app = FastAPI(title="Stepwise")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class IngestReq(BaseModel):
    url: str


@app.post("/ingest")
async def post_ingest(req: IngestReq) -> Plan:
    # TODO: make this a background job + SSE progress stream (GET /ingest/{job}/events)
    return await asyncio.to_thread(ingest, req.url)


@app.get("/plans")
def list_plans():
    return [json.loads(p.read_text()) | {"steps": None} for p in PLANS.glob("*.json")]


@app.get("/plans/{pid}")
def get_plan(pid: str) -> Plan:
    p = PLANS / f"{pid}.json"
    if not p.exists():
        raise HTTPException(404)
    return Plan.model_validate_json(p.read_text())


@app.websocket("/session/{pid}")
async def session(ws: WebSocket, pid: str):
    """
    client -> server:  binary = JPEG frame (~1-2 fps, 512px)
                       text   = {"action": "next"|"skip"|"back"}
    server -> client:  JSON events from Tracker (check, hint, verifying, step_done, ...)
    """
    await ws.accept()
    plan = get_plan(pid)
    tracker, verifier = Tracker(plan), Verifier()
    await ws.send_json({"type": "step_active", "step": 0})

    async def loop():
        while tracker.current < len(plan.steps):
            step = plan.steps[tracker.current]
            if step.verifiable:
                if r := await verifier.check(step):
                    for ev in tracker.on_check(r):
                        await ws.send_json(ev)
            await asyncio.sleep(verifier.interval)

    task = asyncio.create_task(loop())
    try:
        while True:
            msg = await ws.receive()
            if msg.get("bytes"):
                verifier.push(msg["bytes"])
            elif msg.get("text"):
                for ev in tracker.manual(json.loads(msg["text"])["action"]):
                    await ws.send_json(ev)
    except (WebSocketDisconnect, RuntimeError):
        task.cancel()
