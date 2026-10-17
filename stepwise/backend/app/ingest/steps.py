"""Step 2: get an ordered list of step texts, if the source already has them."""
from ..perceptron import mk1_text

SCHEMA = {"type": "object", "properties": {
    "has_explicit_steps": {"type": "boolean"},
    "steps": {"type": "array", "items": {"type": "string"}}},
    "required": ["has_explicit_steps", "steps"]}


def extract_steps(title: str, text: str) -> list[str] | None:
    """Return explicit steps from description/article, or None to let Mk1 discover them."""
    if not text.strip():
        return None
    out = mk1_text(
        f"Tutorial: {title}\n\n{text[:12000]}\n\n"
        "If this text contains an ordered list of instructions, return them as short "
        "imperative steps (merge trivial ones, max ~15). Ignore ads, links, sponsor text. "
        "If there are no explicit instructions, set has_explicit_steps=false.",
        SCHEMA)
    return out["steps"] if out["has_explicit_steps"] and out["steps"] else None
