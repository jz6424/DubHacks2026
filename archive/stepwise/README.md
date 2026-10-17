# Stepwise

Paste a DIY tutorial or recipe link (YouTube or other video, a direct video link, or a written recipe).
Stepwise turns it into a checklist with video timestamps, then watches you through your webcam and
checks off each step, looping the matching part of the video for the step you're on.

Built on **Perceptron Mk1.5**:
- **Processing a tutorial:** reads the video (including on-screen text) and returns steps, substeps,
  timestamps, ingredients, and a camera-checkable "done when" condition for each step.
- **Live checks:** every ~2 s the browser sends the last 4 webcam frames and Mk1.5 judges whether the
  current step's end state is visible. A step is checked off after 2 confident "done" results in a row.

## Run it

Requires Python ≥ 3.10 (via `uv`) and Node.

```bash
cp .env.example .env              # add PERCEPTRON_API_KEY
uv venv --python 3.12 && uv pip install -r backend/requirements.txt
npm --prefix frontend install
```

Two terminals:

```bash
uv run --directory backend uvicorn app.main:app --reload --port 8000
```

```bash
npm --prefix frontend run dev
```

Open http://localhost:5173. Camera access requires `localhost` or HTTPS.

Keyboard: `→`/`Space` done · `←` back · `S` skip.

## Layout

```
backend/app/
  main.py            API: /api/ingest, /api/jobs/{id}, /api/plans, /api/check, /api/media
  ingest.py          background job: fetch -> Mk1.5 -> clean timestamps -> data/plans/<id>.json
  sources.py         YouTube/Vimeo/TikTok (yt-dlp), direct .mp4, articles (schema.org Recipe + text)
  perceptron_api.py  all Mk1.5 calls (plan_from_video, plan_from_text, check_step)
  schemas.py         pydantic models; Draft* are what the model fills in
frontend/src/
  components/        Home, Session, StepVideo, CameraPanel, Checklist, Timer, Finish
  hooks/             useCamera (rolling frame buffer), useStepChecker (polling + debounce)
data/                cached plans and downloaded videos (gitignored)
```

## Tuning knobs

| What | Where |
|---|---|
| Reasoning effort (processing / live) | `.env`: `INGEST_REASONING`, `CHECK_REASONING` |
| Check interval, positives needed, confidence threshold | `useStepChecker` options in `Session.tsx` |
| Frames per check, sample rate | `useCamera(keep, everyMs)` |
| Prompts | `perceptron_api.py` (`PLAN_RULES`, `CHECK_PROMPT`) |
