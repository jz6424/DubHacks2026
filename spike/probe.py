"""Small probe: coordinate scale + latency on 4 frames, and a single-image box detect."""
from perceptron import detect, image, video_frames

from common import MODEL, extract_frames, timed

frames = extract_frames("tesla_kia", fps=4, start=4, end=5)
print("frame size check:", frames[0][0])

timed("probe_image_detect", detect, image(str(frames[0][0])), classes=["car", "truck"],
      model=MODEL, reasoning_effort="low", max_tokens=2048)
timed("probe_frames_track", detect, video_frames([(str(p), t) for p, t in frames]), classes=["car", "truck"],
      model=MODEL, reasoning_effort="low", max_tokens=4096)
