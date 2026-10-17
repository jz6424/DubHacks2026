"""Step 4: turn each step into something a camera can verify.

This is the single biggest accuracy lever. "Cream butter" is not checkable;
"butter and sugar in bowl look pale and fluffy, no visible sugar granules" is.
"""
from ..perceptron import mk1_text

SCHEMA = {"type": "object", "properties": {"steps": {"type": "array", "items": {
    "type": "object", "properties": {
        "title": {"type": "string"},
        "visual_check": {"type": "string"},
        "verifiable": {"type": "boolean"},
        "timer_seconds": {"type": ["integer", "null"]},
        "key_objects": {"type": "array", "items": {"type": "string"}}},
    "required": ["title", "visual_check", "verifiable", "key_objects"]}}}, "required": ["steps"]}

PROMPT = """You are preparing a camera-based step checker for: {title}
For each step write:
- title: <= 6 words, imperative
- visual_check: the observable END STATE that proves the step is done, as seen by a
  webcam pointed at a workspace. Mention objects, positions, colors, shapes.
  Never mention quantities a camera can't measure (1 tsp, 200g) or time.
- verifiable: false if the step can't be seen (preheat oven, wait, wash hands off-camera)
- timer_seconds: if the step is mostly waiting
- key_objects: 1-3 nouns to draw grounding boxes around
Steps:
{steps}"""


def write_checks(title: str, steps: list[str]) -> list[dict]:
    listed = "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps))
    return mk1_text(PROMPT.format(title=title, steps=listed), SCHEMA)["steps"]
