# Stepwise — follow-along DIY coach

Paste a tutorial (YouTube video or written recipe/how-to). Stepwise turns it into a
step plan with timestamps, then watches you through your webcam and checks off
steps as you complete them — looping the matching part of the video for the step
you're on.

Models: **Perceptron Mk1** (offline video understanding, step timestamps) and
**Perceptron Isaac 0.2** (fast per-frame step verification, grounding boxes).

## Layout
```
backend/            FastAPI service
  app/main.py         routes: POST /ingest, GET /plans/{id}, WS /session/{id}
  app/models.py       Step / Plan / CheckResult schemas
  app/perceptron.py   thin client for Mk1 + Isaac (OpenAI-compatible)
  app/ingest/         URL -> plan.json pipeline
  app/live/           webcam verification loop + step state machine
  spikes/             hour-0 go/no-go scripts — RUN THESE FIRST
frontend/           Vite + React UI (ingest screen, session screen)
data/plans/         cached plan.json files (pre-bake demo tutorials here)
DESIGN.md           UI directions + interaction details
```

## Quick start
```bash
cp .env.example .env ak.8bRJDeJTUmvvnLPIkPtL7Q.6EAGndgPcgoEDNEeBf2Q3dLn3Tp8nSC-sIt5XyndvEc
cd backend && pip install -r requirements.txt
python spikes/go_no_go.py "https://youtube.com/watch?v=..."   # validate Mk1 + Isaac
uvicorn app.main:app --reload --port 8000
cd ../frontend && npm install && npm run dev
```

## Status
Scaffold + pseudo-code. Every `TODO(verify)` marks an assumption about the
Perceptron API that the spike scripts must confirm before building on it.
