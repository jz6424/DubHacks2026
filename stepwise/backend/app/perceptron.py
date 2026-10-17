"""Thin wrapper over Perceptron's OpenAI-compatible API.

Everything marked TODO(verify) must be confirmed by spikes/go_no_go.py:
  - how video is attached (video_url content part? file upload? frames?)
  - the exact shape of `annotation_format="clip"` output
  - where Isaac 0.2 is hosted and its model id
"""
import base64, json, os
from openai import OpenAI

_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        if os.getenv("PERCEPTRON_API_KEY"):
            _client = OpenAI(api_key=os.environ["PERCEPTRON_API_KEY"],
                             base_url=os.environ["PERCEPTRON_BASE_URL"])
        else:
            _client = OpenAI(api_key=os.environ["OPENROUTER_API_KEY"],
                             base_url="https://openrouter.ai/api/v1")
    return _client


def _b64(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def mk1_video(video_bytes: bytes, prompt: str, schema: dict | None = None,
              clips: bool = True, reasoning: bool = False) -> dict:
    """Ask Mk1 about a (short, <=~3 min, low-res) video chunk."""
    extra = {}
    if clips:
        extra["annotation_format"] = "clip"          # TODO(verify) param placement
    if reasoning:
        extra["reasoning"] = {"enabled": True}       # TODO(verify)
    resp = client().chat.completions.create(
        model=os.getenv("MK1_MODEL", "perceptron-mk1"),
        messages=[{"role": "user", "content": [
            {"type": "video_url", "video_url": {"url": _b64(video_bytes, "video/mp4")}},  # TODO(verify)
            {"type": "text", "text": prompt},
        ]}],
        response_format=({"type": "json_schema",
                          "json_schema": {"name": "out", "schema": schema}} if schema else None),
        extra_body=extra or None,
    )
    return json.loads(resp.choices[0].message.content)


def mk1_text(prompt: str, schema: dict) -> dict:
    """Text-only structured call (step extraction, visual-check writing)."""
    resp = client().chat.completions.create(
        model=os.getenv("MK1_MODEL", "perceptron-mk1"),
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_schema", "json_schema": {"name": "out", "schema": schema}},
    )
    return json.loads(resp.choices[0].message.content)


def isaac_frames(frames_jpeg: list[bytes], prompt: str, schema: dict) -> dict:
    """Fast multi-frame check. Frames oldest -> newest, ~512px, JPEG q70."""
    content = [{"type": "image_url", "image_url": {"url": _b64(f, "image/jpeg")}} for f in frames_jpeg]
    content.append({"type": "text", "text": prompt})
    resp = client().chat.completions.create(
        model=os.getenv("ISAAC_MODEL", "isaac-0.2-2b"),             # TODO(verify) host/id
        messages=[{"role": "user", "content": content}],
        response_format={"type": "json_schema", "json_schema": {"name": "out", "schema": schema}},
        max_tokens=200,
    )
    return json.loads(resp.choices[0].message.content)
