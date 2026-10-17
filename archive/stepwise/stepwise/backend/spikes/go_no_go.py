"""HOUR 0-2. Run before building anything else. Answers three questions:

 1. Can Mk1 timestamp steps in a real tutorial?   (print segments, eyeball vs video)
 2. Can Isaac tell 'done' from 'not done'?          (webcam stills you capture by hand)
 3. Latency?                                        (Isaac p50 must be < ~1.5 s)

Usage:
  python spikes/go_no_go.py mk1 <youtube_url>
  python spikes/go_no_go.py isaac "<visual check>" before.jpg after.jpg
"""
import sys, time
from pathlib import Path
from dotenv import load_dotenv
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from app.ingest import source, align          # noqa: E402
from app.live.verifier import SCHEMA, PROMPT  # noqa: E402
from app.perceptron import isaac_frames       # noqa: E402

if sys.argv[1] == "mk1":
    raw = source.fetch(sys.argv[2])
    chunk = align.chunk_video(raw.video_path, min(raw.duration, 150))[0]
    t = time.time()
    from app.perceptron import mk1_video
    out = mk1_video(chunk[1], "Segment this tutorial clip into physical steps with start/end seconds.",
                    align.SEG_SCHEMA)
    print(f"{time.time()-t:.1f}s", out)   # compare against https://youtu.be/<id>?t=<start>

elif sys.argv[1] == "isaac":
    check = sys.argv[2]
    for img in sys.argv[3:]:
        t = time.time()
        out = isaac_frames([Path(img).read_bytes()],
                           PROMPT.format(title="test", check=check, objects="main object"), SCHEMA)
        print(f"{img}: {time.time()-t:.2f}s", out)   # want: before=False, after=True
