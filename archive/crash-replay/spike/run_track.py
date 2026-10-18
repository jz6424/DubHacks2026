"""(a) Tracking: native Mk1.5 tracks over video_frames vs per-frame detection, for one clip."""
import sys
from concurrent.futures import ThreadPoolExecutor

from perceptron import detect, image, video_frames

from common import MODEL, extract_frames, timed

CLASSES = ["car", "truck", "bus", "motorcycle", "bicycle", "person"]

clip, mode = sys.argv[1], sys.argv[2]
start, end = float(sys.argv[3]), float(sys.argv[4])
fps = float(sys.argv[5]) if len(sys.argv) > 5 else 4
effort = sys.argv[6] if len(sys.argv) > 6 else "low"
frames = extract_frames(clip, fps=fps, start=start, end=end)
print(clip, mode, len(frames), "frames", effort)

if mode == "native":
    win = 16  # 16 frames x ~20 objects x ~20 tokens/waypoint stays under the 8192 completion-token cap
    def chunk(i):
        sub = frames[max(0, i - 1): i + win]  # 1-frame overlap for stitching
        return timed(f"track_native_{clip}_{fps:g}fps_{effort}_w{i:03d}", detect,
                     video_frames([(str(p), t) for p, t in sub]),
                     classes=CLASSES, model=MODEL, reasoning_effort=effort, max_tokens=8192)
    with ThreadPoolExecutor(3) as ex:
        list(ex.map(chunk, range(0, len(frames), win)))
else:
    def one(pt):
        p, t = pt
        return timed(f"det_{clip}_{t:06d}_{effort}", detect, image(str(p)), classes=CLASSES,
                     model=MODEL, reasoning_effort=effort, max_tokens=4096)
    with ThreadPoolExecutor(3) as ex:
        list(ex.map(one, frames))
