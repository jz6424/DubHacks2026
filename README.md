# Crash Replay

Upload dashcam footage of a collision and get a synced replay: tracked road users on the video, a top-down
reconstruction with speeds and uncertainty ranges, and (coming) an event timeline and an evidence-cited claim draft.

**AI-generated draft for review. Not a legal determination or professional reconstruction.**

## How it works
| stage | what | how |
|---|---|---|
| ingest | browser-safe MP4 + 4 fps frames | ffmpeg |
| detect | boxes per frame | Perceptron Mk1.5 (`detect`, reasoning off) |
| track | stable IDs | IoU + Hungarian, gap repair, optional `overrides.json` |
| ocr | dashcam speed/time/GPS overlay | Mk1.5 structured output, 1 frame/s |
| geometry | camera height, scale, ego speed, road positions, speeds ± 95% | lane lines + dash spacing, Kalman smoothing |
| scene | one JSON for the UI | merge |

Every stage is cached in `data/clips/<id>/stages/*.json`; model calls are cached per frame, so re-runs are free.
Design notes and measured model behaviour: [spike/README.md](spike/README.md).

## Run
```bash
cp .env.example .env                      # add PERCEPTRON_API_KEY
uv venv --python 3.12 && uv pip install -r backend/requirements.txt
npm --prefix frontend install
.venv/bin/python backend/scripts/fetch_curated.py           # demo clips (public domain)
.venv/bin/python backend/scripts/run_pipeline.py tesla-kia  # ~1 min, ~$0.05 of model calls
.venv/bin/uvicorn --app-dir backend app.main:app --reload --port 8000
npm --prefix frontend run dev                                # http://localhost:5173/#tesla-kia@12
```

The previous project (Stepwise) is archived in `archive/stepwise/`.
