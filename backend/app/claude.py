"""All Claude calls. The spec (prompts/huskymatch_system.md) is the system prompt for every call; a short app-mode
addendum per task says which phase the app needs from this call, since the app itself runs onboarding and swiping.

Research uses the server-side web_search / web_fetch tools plus one client tool, add_club_card, whose strict schema is
the spec's card JSON: each verified club arrives as soon as it's found, so the UI can show progress and the student
can start swiping before research finishes.
"""
import json
import threading
import time
from datetime import date
from typing import Any, Callable

import anthropic

from .config import MODEL, SYSTEM_PROMPT_FILE
from .profile import INTERESTS

client = anthropic.Anthropic(max_retries=3)
SPEC = SYSTEM_PROMPT_FILE.read_text()

# Refusal fallbacks: on a safety decline the API re-runs the request on a suitable model inside the same call.
FALLBACK = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}

RESEARCH_MODE = """

## App mode: research (Phase 2 only)
You are running inside the Me&UDub app, not a chat. The app already ran Phase 1 (the student's profile is in the
user message as JSON) and runs the swiping and results screens itself. Do Phase 2 for the slice of interests you're
given, and hand each club to the app with the add_club_card tool.

- Research real, currently active clubs at the student's campus. HuskyLink pages (huskylink.washington.edu) render in
  the browser and usually can't be read directly, so find HuskyLink entries through web search, then read the club's
  own website, Linktree, department pages and other public pages for details. Instagram usually requires login: use
  what search results show from public posts and bios; never try to log in.
- Call add_club_card as soon as a club is verified: one call per club, don't batch them up at the end.
- Every fact must come from a page or search result you actually saw; list those URLs in `sources` (checked = today's
  date from the user message). If you couldn't confirm a field, write "couldn't confirm" (or "unknown" for dates).
  Never guess. Estimates (usually hours/week) set commitment.estimated = true and say what they're based on.
- Each card's `sources` and `last_active.source` must be pages about that club (its own site, HuskyLink entry,
  social page, or a page that names it). You'll research several clubs in one conversation: don't carry URLs over
  from a different club, and leave out general pages (careers, department homepages) that don't mention it.
- `last_active` is the most recent dated sign of activity you saw (event, post, announcement) and its URL. Look for
  one: it's what tells the student the club is real and running. status: "active" if it's within about 6 months,
  "may_be_inactive" if it's older (or you saw a direct sign, like an 'inactive' badge), "unverified" if you found no
  dated activity at all. The app re-checks status against the date.
- Dues and hours: look in the club's FAQ, "join"/membership page, constitution and HuskyLink description before giving
  up. If the club's own membership info never mentions dues, write "No dues listed (confirm with officers)" rather
  than "couldn't confirm". For hours_per_week, if you know the meeting schedule, put an estimate like "~2 hrs/wk"
  with estimated = true and say what it's based on in meeting_schedule; keep hours_per_week itself short.
- Each card needs at least 2 sources and at least one of dues, hours or meeting schedule confirmed; add_club_card
  refuses thinner cards. A directory listing (e.g. the rec-clubs list) is good for finding candidates, but then read
  the club's own page (website, sites.uw.edu, Linktree) to fill in the details.
- Only include identity-based clubs if the student's interests include "Cultural/identity-based communities".
- Respect the student's dues budget, commitment level and experience preference when choosing clubs. With strict
  preferences, near-misses are expected: a club that misses one (small dues, a bit more time, a light application)
  is fine if fit_reason says so in a few words. Prefer a near-miss over coming back short.
- fit_reason is ONE short sentence (at most 18 words) that names the one or two strongest matches with the student's
  answers. It is shown on the card front, so anything longer gets cut off.
- Budget: roughly 10 web searches and 10 page fetches for your whole slice. Keep going until you've added your
  target number of cards or used the budget, then stop and reply with one short sentence.
- If add_club_card answers that a club is a duplicate, pick a different club.
- `interest_areas`: every one of the app's interest areas the club genuinely fits (not just your slice), so other
  students can find it later. A wildcard still gets the areas it actually belongs to.
- The user message may list clubs already verified recently ("known clubs"). For each one that fits this student,
  call use_known_club with a fit_reason for this student: no searching needed. Don't re-research or re-add those with
  add_club_card. Spend your search budget only on finding the rest of your target.
"""

MORE_MODE = """

## App mode: "Tell me more" (Phase 3)
The student tapped ❓ on one card (given as JSON). Give 3-5 extra details that matter for deciding whether to join,
tied to the student's profile where possible: recent events, what a typical meeting looks like, how to get started,
anything surprising. Use at most 3 web searches and 3 page fetches. Short bullet points, each with its source. If you
can't find more, say so plainly. No swipe instructions; the app shows the buttons.
"""

RESULTS_MODE = """

## App mode: match results (Phase 4)
The app shows each matched club's card details itself (join steps, dues, links, sources). Return only what needs
judgment, as JSON: for each match, any conflicts with the student's availability and the "good to know" tips; then an
action plan ordered by urgency (earliest deadlines and first steps this week). Use only the card data provided: no new
facts, and say "unknown" rather than guess deadlines. Remind them to confirm deadlines with the club directly.
"""

DRAFT_MODE = """

## App mode: draft a message (Phase 4)
Write a short, friendly first message from the student to one club (DM or email), 60-110 words, in the student's
voice. Mention why they're interested (from their profile), ask the one or two things they'd need to know to join
(from what the card couldn't confirm), and don't invent anything about the student beyond the profile. Plain text only.
"""


def _system(mode: str) -> list[dict]:
    # Spec first and identical every call, so it is served from the prompt cache across all calls and students.
    return [{"type": "text", "text": SPEC, "cache_control": {"type": "ephemeral"}}, {"type": "text", "text": mode}]


CARD_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["club_id", "name", "category", "category_emoji", "description", "commitment", "dues",
                 "meeting_schedule", "join_type", "fit_reason", "wildcard", "status", "last_active", "links",
                 "application", "sources", "interest_areas"],
    "properties": {
        "club_id": {"type": "string", "description": "lowercase-hyphenated slug of the club name"},
        "name": {"type": "string"},
        "category": {"type": "string"},
        "category_emoji": {"type": "string"},
        "description": {"type": "string", "description": "1-2 sentences"},
        "commitment": {
            "type": "object", "additionalProperties": False, "required": ["level", "hours_per_week", "estimated"],
            "properties": {
                "level": {"type": "string", "enum": ["casual", "regular", "committed", "all_in"]},
                "hours_per_week": {"type": "string", "description": "e.g. '2-3 hrs/wk'"},
                "estimated": {"type": "boolean"},
            },
        },
        "dues": {"type": "string"},
        "meeting_schedule": {"type": "string"},
        "join_type": {"type": "string", "enum": ["open", "application", "tryout", "interview", "unknown"]},
        "fit_reason": {"type": "string", "description": "ONE short sentence (at most 18 words) naming the one or two strongest matches with this student's answers, e.g. \"Weekend robot builds that give a CS sophomore real résumé projects.\" No lists, no hedging; mention a near-miss only if it matters."},
        "wildcard": {"type": "boolean"},
        "interest_areas": {"type": "array", "items": {"type": "string", "enum": INTERESTS},
                           "description": "every app interest area this club fits"},
        "status": {"type": "string", "enum": ["active", "may_be_inactive", "unverified"]},
        "last_active": {
            "type": "object", "additionalProperties": False, "required": ["date", "source"],
            "properties": {"date": {"type": "string", "description": "YYYY-MM-DD or 'unknown'"},
                           "source": {"type": "string"}},
        },
        "links": {
            "type": "object", "additionalProperties": False, "required": ["huskylink", "website", "instagram"],
            "properties": {"huskylink": {"type": "string"}, "website": {"type": "string"},
                           "instagram": {"type": "string"}},
        },
        "application": {
            "type": "object", "additionalProperties": False, "required": ["deadline", "url", "steps"],
            "properties": {"deadline": {"type": "string"}, "url": {"type": "string"},
                           "steps": {"type": "array", "items": {"type": "string"}}},
        },
        "sources": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": False, "required": ["url", "checked"],
                      "properties": {"url": {"type": "string"}, "checked": {"type": "string"}}},
        },
    },
}

ADD_CARD_TOOL = {
    "name": "add_club_card",
    "description": "Hand one verified club to the app as a swipe card. Call once per club as soon as it is verified.",
    "strict": True,
    "input_schema": CARD_SCHEMA,
}

USE_KNOWN_TOOL = {
    "name": "use_known_club",
    "description": "Add one of the known (already verified) clubs from the user message as a swipe card for this student.",
    "strict": True,
    "input_schema": {
        "type": "object", "additionalProperties": False, "required": ["club_id", "fit_reason", "wildcard"],
        "properties": {"club_id": {"type": "string", "description": "club_id exactly as listed in known clubs"},
                       "fit_reason": {"type": "string", "description": "ONE short sentence (at most 18 words) naming the one or two strongest matches with this student's answers, e.g. \"Weekend robot builds that give a CS sophomore real résumé projects.\" No lists, no hedging; mention a near-miss only if it matters."},
                       "wildcard": {"type": "boolean"}},
    },
}


def _brief(card: dict) -> dict:
    """What a researcher needs to judge fit for a known club, without the full card."""
    c = card.get("commitment") or {}
    return {"club_id": card["club_id"], "name": card["name"], "category": card.get("category"),
            "interest_areas": card.get("interest_areas"), "description": card.get("description"),
            "commitment": f"{c.get('level')}, {c.get('hours_per_week')}", "dues": card.get("dues"),
            "meeting_schedule": card.get("meeting_schedule"), "join_type": card.get("join_type"),
            "status": card.get("status")}


def _web_tools(searches: int, fetches: int) -> list[dict]:
    return [{"type": "web_search_20260209", "name": "web_search", "max_uses": searches},
            {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": fetches}]


class Usage:
    """Running totals for one job, for the cost readout."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.input = self.output = self.cache_read = self.cache_write = self.searches = self.fetches = 0

    def add(self, u: Any) -> None:
        with self.lock:
            self.input += u.input_tokens or 0
            self.output += u.output_tokens or 0
            self.cache_read += getattr(u, "cache_read_input_tokens", 0) or 0
            self.cache_write += getattr(u, "cache_creation_input_tokens", 0) or 0
            stu = getattr(u, "server_tool_use", None)
            if stu:
                self.searches += getattr(stu, "web_search_requests", 0) or 0
                self.fetches += getattr(stu, "web_fetch_requests", 0) or 0

    def dollars(self) -> float:
        # Opus 5.5 list prices: $4 / $20 per MTok, cache reads $0.20, 5-minute cache writes 1.25x input; search $10/1k
        return round(self.input * 4e-6 + self.output * 20e-6 + self.cache_read * 0.2e-6 + self.cache_write * 5e-6
                     + self.searches * 0.01, 3)

    def as_dict(self) -> dict:
        return {"input_tokens": self.input, "output_tokens": self.output, "cache_read_tokens": self.cache_read,
                "cache_write_tokens": self.cache_write, "web_searches": self.searches, "web_fetches": self.fetches,
                "est_cost_usd": self.dollars()}


def _stream_turn(params: dict, on_action: Callable[[str], None], usage: Usage):
    """One model turn, streamed so the app can show what the researcher is doing (search queries, pages read)."""
    pending: dict[int, dict] = {}
    with client.beta.messages.stream(**params, **FALLBACK) as stream:
        for event in stream:
            try:
                if event.type == "content_block_start" and event.content_block.type == "server_tool_use":
                    pending[event.index] = {"name": event.content_block.name, "json": ""}
                elif event.type == "content_block_delta" and event.index in pending \
                        and getattr(event.delta, "type", "") == "input_json_delta":
                    pending[event.index]["json"] += event.delta.partial_json
                elif event.type == "content_block_stop" and event.index in pending:
                    p = pending.pop(event.index)
                    args = json.loads(p["json"] or "{}")
                    if p["name"] == "web_search" and args.get("query"):
                        on_action(f"🔎 Searching: {args['query']}")
                    elif p["name"] == "web_fetch" and args.get("url"):
                        on_action(f"📄 Reading: {args['url']}")
            except Exception:  # noqa: BLE001 - progress display must never break a research run
                pass
        msg = stream.get_final_message()
    usage.add(msg.usage)
    return msg


def research(profile: dict, slice_interests: list[str], target: int, wildcards: int,
             add_card: Callable[[dict], str], on_action: Callable[[str], None], usage: Usage,
             should_stop: Callable[[], bool], known: list[dict] | None = None,
             use_known: Callable[[str, str, bool], str] | None = None,
             max_turns: int = 40, max_seconds: float = 420) -> str:
    """One research agent for one slice of interests. Returns how it ended. `known` are fresh catalog clubs for this
    slice; the agent adds the ones that fit via use_known(club_id, fit_reason, wildcard) instead of searching."""
    known = known or []
    ask = (f"Today's date: {date.today().isoformat()}\n"
           f"Student profile (from onboarding):\n{json.dumps(profile, indent=1)}\n\n"
           f"Your slice: find about {target} clubs for these interest areas: {json.dumps(slice_interests)}."
           + (f" Also include {wildcards} labeled wildcard pick(s) outside their stated interests (not identity-based)."
              if wildcards else "")
           + " Other researchers are covering the student's other interests at the same time."
           + (f"\n\nKnown clubs (verified in the last few weeks; use_known_club for the ones that fit):\n"
              f"{json.dumps([_brief(k) for k in known], indent=1)}" if known else ""))
    tools = [*_web_tools(6, 6), ADD_CARD_TOOL] + ([USE_KNOWN_TOOL] if known and use_known else [])
    messages: list[dict] = [{"role": "user", "content": ask}]
    t0 = time.time()
    saved, nudged = 0, False
    for _ in range(max_turns):
        if should_stop() or time.time() - t0 > max_seconds:
            return "stopped (time limit)" if not should_stop() else "stopped"
        # Automatic caching moves a breakpoint to the end of the growing conversation each turn, so earlier
        # turns (search results and pages read) are cache reads instead of full-price input on every turn.
        msg = _stream_turn(dict(model=MODEL, max_tokens=16000, system=_system(RESEARCH_MODE),
                                cache_control={"type": "ephemeral"},
                                output_config={"effort": "medium"}, messages=messages,
                                tools=tools), on_action, usage)
        messages.append({"role": "assistant", "content": msg.content})
        if msg.stop_reason == "refusal":
            return "refused"
        if msg.stop_reason == "pause_turn":
            continue  # long server-tool turn: re-send to let it continue
        calls = [b for b in msg.content if b.type == "tool_use"]
        if not calls:
            if saved < target and not nudged and time.time() - t0 < max_seconds * 0.7:
                nudged = True  # researchers tend to stop early under strict preferences
                messages.append({"role": "user", "content": (
                    f"You've added {saved} of your target {target} cards. If you have search budget left, keep going: "
                    "near-miss clubs are fine when fit_reason says what doesn't match. If you truly found no more, "
                    "reply with one short sentence.")})
                continue
            return "done"
        if msg.stop_reason == "max_tokens":
            return "stopped (output cut off)"  # a truncated tool input must not be run
        results = []
        for b in calls:
            if not isinstance(b.input, dict):
                out = None
            elif b.name == "add_club_card":
                out = add_card(b.input)
            elif b.name == "use_known_club" and use_known:
                out = use_known(b.input["club_id"], b.input["fit_reason"], b.input["wildcard"])
            else:
                out = None
            saved += bool(out and out.startswith("Saved"))
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": out}
                           if out is not None else
                           {"type": "tool_result", "tool_use_id": b.id, "is_error": True, "content": "unknown tool"})
        messages.append({"role": "user", "content": results})
    return "stopped (turn limit)"


def tell_more(profile: dict, card: dict, usage: Usage) -> dict:
    """Extra details for one card, with the sources the model cited."""
    msg = _stream_turn(dict(model=MODEL, max_tokens=8000, system=_system(MORE_MODE),
                            output_config={"effort": "low"}, tools=_web_tools(3, 3),
                            messages=[{"role": "user", "content": f"Student profile:\n{json.dumps(profile)}\n\n"
                                                                  f"Card:\n{json.dumps(card)}"}]),
                       lambda _: None, usage)
    text, cites = [], {}
    for b in msg.content:
        if b.type == "text":
            text.append(b.text)
            for c in (getattr(b, "citations", None) or []):
                url = getattr(c, "url", None)
                if url:
                    cites[url] = getattr(c, "title", None) or url
    if not cites:  # model named sources inline without citing: fall back to the pages it read, then searched
        cites = _seen_pages(msg.content, limit=5)
    return {"text": "".join(text).strip(), "sources": [{"url": u, "title": t} for u, t in cites.items()]}


def _seen_pages(content: list, limit: int) -> dict[str, str]:
    """url -> title for pages from this turn's server tool results: fetched pages first, then search results."""
    fetched, searched = {}, {}
    for b in content:
        if b.type == "web_fetch_tool_result" and getattr(b.content, "type", "") == "web_fetch_result":
            doc = getattr(b.content, "content", None)
            fetched.setdefault(b.content.url, getattr(doc, "title", None) or b.content.url)
        elif b.type == "web_search_tool_result" and isinstance(b.content, list):
            for r in b.content:
                if getattr(r, "type", "") == "web_search_result":
                    searched.setdefault(r.url, r.title or r.url)
    out = dict(fetched)
    for u, t in searched.items():
        if len(out) >= limit:
            break
        out.setdefault(u, t)
    return dict(list(out.items())[:max(limit, len(fetched))])


RESULTS_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["clubs", "action_plan"],
    "properties": {
        "clubs": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["club_id", "availability_conflicts", "good_to_know"],
            "properties": {"club_id": {"type": "string"},
                           "availability_conflicts": {"type": "string", "description": "'none' if no conflict"},
                           "good_to_know": {"type": "array", "items": {"type": "string"}}}}},
        "action_plan": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["when", "step", "club_id"],
            "properties": {"when": {"type": "string"}, "step": {"type": "string"}, "club_id": {"type": "string"}}}},
    },
}


def results(profile: dict, matches: list[dict], usage: Usage) -> dict:
    msg = _stream_turn(dict(model=MODEL, max_tokens=16000, system=_system(RESULTS_MODE),
                            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": RESULTS_SCHEMA}},
                            messages=[{"role": "user", "content": f"Today's date: {date.today().isoformat()}\n"
                                                                  f"Student profile:\n{json.dumps(profile)}\n\n"
                                                                  f"Matched clubs (super-likes first):\n"
                                                                  f"{json.dumps(matches)}"}]),
                       lambda _: None, usage)
    if msg.stop_reason == "refusal":
        raise RuntimeError("the model declined to write results")
    return json.loads(next(b.text for b in msg.content if b.type == "text"))


def draft_message(profile: dict, card: dict, usage: Usage) -> str:
    msg = _stream_turn(dict(model=MODEL, max_tokens=4000, system=_system(DRAFT_MODE), output_config={"effort": "low"},
                            messages=[{"role": "user", "content": f"Student profile:\n{json.dumps(profile)}\n\n"
                                                                  f"Club card:\n{json.dumps(card)}"}]),
                       lambda _: None, usage)
    return "".join(b.text for b in msg.content if b.type == "text").strip()
