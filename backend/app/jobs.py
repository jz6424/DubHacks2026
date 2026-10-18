"""Research jobs: one per student profile. Runs parallel research agents (one per slice of interests), collects cards
as they arrive (de-duplicated across agents), and keeps progress, cost and later results on disk so a repeated profile
(e.g. the demo) loads instantly."""
import json
import re
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any

from . import catalog, claude, images, limits
from .config import JOBS, RESEARCHERS, TARGET_CARDS
from .profile import IDENTITY_INTEREST, INTERESTS, Profile

_lock = threading.RLock()
_running: set[str] = set()


_norm = catalog.norm


INACTIVE_AFTER_DAYS = 183


def _unconfirmed(text: str) -> bool:
    t = (text or "").lower()
    return not t.strip() or "couldn't confirm" in t or "could not confirm" in t or t.strip() == "unknown"


def thin_card(card: dict, allow_partial: bool = False) -> str | None:
    """Why a newly researched card is too thin to show, or None. Reused catalog cards passed this when first added.
    allow_partial: only require the 2 sources (for active clubs imported by hand whose pages don't list dues, hours or
    a schedule; they rank below fully described clubs)."""
    urls = {s.get("url", "").rstrip("/") for s in card.get("sources") or [] if s.get("url")}
    if len(urls) < 2:
        return ("Not added: a card needs at least 2 sources. Read the club's own page (website, sites.uw.edu, "
                "Linktree, Instagram bio via search) and add it, or pick a better-documented club.")
    if not allow_partial and all(_unconfirmed(x) for x in (card.get("dues"), (card.get("commitment") or {}).get("hours_per_week"),
                                     card.get("meeting_schedule"))):
        return ("Not added: dues, hours and meeting schedule are all unconfirmed. Find at least one on the club's own "
                "page (an estimate from a known meeting schedule counts), or pick a better-documented club.")
    return None


def detail_level(card: dict) -> str:
    """"full" when dues, hours and meeting schedule are all confirmed, else "partial" (for deck ordering)."""
    fields = (card.get("dues"), (card.get("commitment") or {}).get("hours_per_week"), card.get("meeting_schedule"))
    return "partial" if any(_unconfirmed(x) for x in fields) else "full"


def card_status(card: dict, today: date | None = None) -> str:
    """active | may_be_inactive | unverified, from last_active.date. No dated activity found is "unverified", not
    "may be inactive"; a date older than ~6 months is "may_be_inactive"; a recent date keeps the researcher's call
    (it may have seen other signs, like a HuskyLink 'inactive' badge)."""
    try:
        seen = date.fromisoformat(str((card.get("last_active") or {}).get("date", ""))[:10])
    except ValueError:
        return "unverified"
    if ((today or date.today()) - seen).days > INACTIVE_AFTER_DAYS:
        return "may_be_inactive"
    return "may_be_inactive" if card.get("status") == "may_be_inactive" else "active"


def vet_card(card: dict, check_thin: bool = True, allow_partial: bool = False) -> tuple[dict, str | None]:
    """Normalize a researched card (club_id slug, status from the date) and say why it's too thin to keep, if it is."""
    card = {**card, "club_id": re.sub(r"[^a-z0-9-]+", "-", card["club_id"].lower()).strip("-") or uuid.uuid4().hex[:8]}
    card["status"] = card_status(card)
    return card, (thin_card(card, allow_partial) if check_thin else None)


CATALOG_ONLY_MARGIN = 3  # a researcher with this many more known clubs than its share skips web search


def _path(job_id: str):
    return JOBS / f"{job_id}.json"


def load(job_id: str) -> dict | None:
    if not re.fullmatch(r"[a-z0-9]{8,32}", job_id):
        return None
    p = _path(job_id)
    return json.loads(p.read_text()) if p.exists() else None


def save(job: dict) -> None:
    JOBS.mkdir(parents=True, exist_ok=True)
    tmp = _path(job["id"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(job, indent=1))
    tmp.replace(_path(job["id"]))


def job_files() -> list:
    """Job files, newest first. Skips macOS "._" metadata files and anything unreadable, so a stray file in the
    folder can't break starting jobs."""
    if not JOBS.exists():
        return []
    return sorted((p for p in JOBS.glob("*.json") if not p.name.startswith(".")),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def read_job(p) -> dict | None:
    try:
        job = json.loads(p.read_text())
        return job if isinstance(job, dict) and "profile" in job else None
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def find_by_profile(key: str) -> dict | None:
    for p in job_files():
        job = read_job(p)
        if job and job.get("profile_key") == key and job.get("status") in ("done", "researching"):
            return job
    return None


def slices(profile: Profile, n: int) -> list[list[str]]:
    """Split the student's interests across n researchers (round-robin, so each gets a mix)."""
    chosen = [i for i in profile.interests if i in INTERESTS]
    if not chosen:  # "not sure": spread across popular, non-identity areas
        chosen = [i for i in INTERESTS if i != IDENTITY_INTEREST and "Greek" not in i and "Faith" not in i]
    k = max(1, min(n, len(chosen)))
    return [chosen[i::k] for i in range(k)]


def start(profile: Profile, force: bool = False, ip: str | None = None) -> dict:
    """Reuse research for an identical profile, else start a new run. A new run from a visitor (ip given) must pass
    the spend limits first: raises limits.LimitHit."""
    key = profile.key()
    if not force:
        existing = find_by_profile(key)
        if existing:
            return existing
    job_id = uuid.uuid4().hex[:12]
    if ip is not None:
        limits.reserve_job(ip, job_id)
    job = {"id": job_id, "profile_key": key, "profile": profile.model_dump(),
           "summary": profile.summary(), "status": "researching", "created": time.time(), "cards": [],
           "actions": [], "researchers": [], "usage": {}, "more": {}, "results": {}, "drafts": {}, "error": None}
    save(job)
    threading.Thread(target=_run, args=(job["id"],), daemon=True).start()
    return job


def _update(job_id: str, fn) -> dict:
    with _lock:
        job = load(job_id)
        fn(job)
        save(job)
        return job


def _run(job_id: str) -> None:
    with _lock:
        if job_id in _running:
            return
        _running.add(job_id)
    usage = claude.Usage()
    try:
        job = load(job_id)
        profile = Profile(**job["profile"])
        parts = slices(profile, RESEARCHERS)
        per = max(4, round(TARGET_CARDS / len(parts)))
        campus = catalog.campus_of(job["profile"])

        # Fresh catalog clubs for each slice; a club tagged with several slices goes to the first one only.
        known: list[dict[str, dict]] = []
        taken: set[str] = set()
        for part in parts:
            mine = {}
            for c in catalog.known(campus, part, profile.identity_opt_in()):
                if _norm(c["name"]) not in taken and not thin_card(c, allow_partial=True):  # 1-source ones predate it
                    taken.add(_norm(c["name"]))
                    mine[c["club_id"]] = c
            known.append(mine)
        caps = [per + (1 if i == 0 else 0) for i in range(len(parts))]  # researcher 0 also adds the wildcard
        # Enough known clubs for a slice: pick from the catalog without web search (cheap and fast).
        catalog_only = [len(known[i]) >= caps[i] + CATALOG_ONLY_MARGIN for i in range(len(parts))]
        if catalog_only[0]:  # its wildcard then also comes from the catalog: a few clubs from other areas
            others = [x for x in INTERESTS if x not in profile.interests and x != IDENTITY_INTEREST]
            for c in catalog.known(campus, others, False, limit=12):
                if _norm(c["name"]) not in taken and not thin_card(c, allow_partial=True) and len(known[0]) < 46:
                    taken.add(_norm(c["name"]))
                    known[0][c["club_id"]] = c
        if taken:
            note = f"📚 {len(taken)} clubs already in the catalog for these interests" + (
                " (picking from those, no web search)" if all(catalog_only) else "")
            _update(job_id, lambda j: j.__setitem__("actions", (j["actions"] + [note])[-40:]))
        counts = [0] * len(parts)

        def add_card(i: int, card: dict, reused: bool = False) -> str:
            if counts[i] >= caps[i]:
                return (f"Not added: you've already reached your target of {caps[i]} cards. "
                        "Stop now and reply with one short sentence.")
            card, why = vet_card(card, check_thin=not reused)
            if why:
                on_action(f"↩️ Sent back {card['name']} for more detail")
                return why
            if not reused:
                try:
                    catalog.upsert(campus, card)
                except Exception:  # noqa: BLE001 - the catalog is a cache; never lose a card over it
                    traceback.print_exc()
            images.ensure_async(campus, card)  # no-op if the club already has one; cards gain it on a later poll
            result = {}

            def put(j):
                names = {_norm(c["name"]) for c in j["cards"]}
                if _norm(card["name"]) in names:
                    result["msg"] = f"Duplicate: {card['name']} was already added by another researcher. Pick a different club."
                    return
                if any(c["club_id"] == card["club_id"] for c in j["cards"]):
                    card["club_id"] += f"-{len(j['cards'])}"
                j["cards"].append(card)
                j["actions"] = (j["actions"] + [f"{'♻️ Reused' if reused else '✅ Added'} {card['name']}"])[-40:]
                counts[i] += 1
                left = caps[i] - counts[i]
                result["msg"] = f"Saved ({left} more to reach your target)." if left else \
                    "Saved. That's your target: stop now and reply with one short sentence."

            _update(job_id, put)
            return result["msg"]

        def book_cost() -> None:
            try:
                limits.set_research_cost(job_id, job["created"], usage.dollars())
            except Exception:  # noqa: BLE001 - bookkeeping must never break a research run
                traceback.print_exc()

        def on_action(text: str) -> None:  # called on every search and page read, so spend stays current
            _update(job_id, lambda j: j.__setitem__("actions", (j["actions"] + [text])[-40:]))
            book_cost()

        def use_known(i: int, club_id: str, fit_reason: str, wildcard: bool) -> str:
            club = known[i].get(club_id)
            if not club:
                return f"No known club with club_id {club_id!r}; use a club_id from the known clubs list."
            return add_card(i, {**club, "fit_reason": fit_reason, "wildcard": wildcard}, reused=True)

        def worker(i: int) -> str:
            try:
                return claude.research(job["profile"], parts[i], per, wildcards=1 if i == 0 else 0,
                                       add_card=lambda card: add_card(i, card),
                                       on_action=on_action, usage=usage, should_stop=lambda: False,
                                       known=list(known[i].values()),
                                       use_known=lambda cid, why, wild: use_known(i, cid, why, wild),
                                       catalog_only=catalog_only[i])
            except Exception as e:  # noqa: BLE001 - one failed researcher shouldn't sink the others
                traceback.print_exc()
                return f"error: {type(e).__name__}: {str(e)[:200]}"
            finally:
                _update(job_id, lambda j: j.__setitem__("usage", usage.as_dict()))
                book_cost()

        with ThreadPoolExecutor(len(parts)) as ex:
            outcomes = list(ex.map(worker, range(len(parts))))

        def finish(j):
            j["researchers"] = [{"interests": p, "outcome": o} for p, o in zip(parts, outcomes)]
            j["usage"] = usage.as_dict()
            if j["cards"]:
                j["status"] = "done"
            else:
                j["status"] = "error"
                j["error"] = "No clubs found: " + "; ".join(outcomes)
        _update(job_id, finish)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        _update(job_id, lambda j: j.update(status="error", error=f"{type(e).__name__}: {str(e)[:300]}"))
    finally:
        with _lock:
            _running.discard(job_id)


def is_running(job_id: str) -> bool:
    with _lock:
        return job_id in _running


def tell_more(job_id: str, club_id: str) -> dict:
    job = load(job_id)
    if job["more"].get(club_id, {}).get("sources"):  # an answer cached without sources predates the fallback
        return job["more"][club_id]
    card = next(c for c in job["cards"] if c["club_id"] == club_id)
    out = _paid(job_id, "more", lambda usage: claude.tell_more(job["profile"], card, usage))
    _update(job_id, lambda j: j["more"].__setitem__(club_id, out))
    return out


def _paid(job_id: str, kind: str, call):
    """Run one of the cheap per-card model calls under the daily budget, and book what it cost (even if it fails)."""
    limits.check_budget()
    usage = claude.Usage()
    try:
        return call(usage)
    finally:
        _update(job_id, lambda j: _add_usage(j, usage))
        limits.add_cost(job_id, kind, usage.dollars())


def _add_usage(job: dict, usage: "claude.Usage") -> None:
    u = job.get("usage") or {}
    for k, v in usage.as_dict().items():
        u[k] = round(u.get(k, 0) + v, 3)
    job["usage"] = u


HOURS_RE = re.compile(r"(\d+(?:\.\d+)?)(?:\s*(?:-|–|to)\s*(\d+(?:\.\d+)?))?")


def hours_estimate(text: str) -> float | None:
    """'2-3 hrs/wk' -> 2.5; '10+ hours' -> 10; unknown -> None."""
    m = HOURS_RE.search(text or "")
    if not m:
        return None
    lo = float(m.group(1))
    hi = float(m.group(2)) if m.group(2) else lo
    return (lo + hi) / 2


RESULTS_VERSION = "v2"  # bump when RESULTS_MODE changes, so results cached under the old prompt are regenerated


def results(job_id: str, swipes: list[dict]) -> dict:
    """Phase 4. Matches = right + super swipes (super first). Cached per set of matches."""
    from .profile import COMMITMENT_MAX_HOURS

    job = load(job_id)
    cards = {c["club_id"]: c for c in job["cards"]}
    supers = [s["club_id"] for s in swipes if s["action"] == "super" and s["club_id"] in cards]
    rights = [s["club_id"] for s in swipes if s["action"] == "right" and s["club_id"] in cards and s["club_id"] not in supers]
    order = list(dict.fromkeys(supers + rights))
    key = RESULTS_VERSION + ":" + ",".join(order)
    if key in job["results"]:
        return job["results"][key]
    matches = [{**cards[i], "super_like": i in supers} for i in order]
    judged = _paid(job_id, "results", lambda usage: claude.results(job["profile"], matches, usage)) if matches \
        else {"clubs": [], "action_plan": []}
    per = [hours_estimate(c["commitment"]["hours_per_week"]) for c in matches]
    known = [h for h in per if h is not None]
    limit = COMMITMENT_MAX_HOURS.get(job["profile"].get("commitment") or "", None)
    total = round(sum(known), 1)
    out = {
        "order": order,
        "judged": judged,
        "hours": {"total": total, "unknown": len(per) - len(known), "limit": limit,
                  "over": bool(limit is not None and total > limit)},
    }
    _update(job_id, lambda j: j["results"].__setitem__(key, out))
    return out


def draft(job_id: str, club_id: str) -> str:
    job = load(job_id)
    if club_id in job["drafts"]:
        return job["drafts"][club_id]
    card = next(c for c in job["cards"] if c["club_id"] == club_id)
    text = _paid(job_id, "draft", lambda usage: claude.draft_message(job["profile"], card, usage))
    _update(job_id, lambda j: j["drafts"].__setitem__(club_id, text))
    return text


def public(job: dict) -> dict:
    """What the frontend gets: everything except bulky internals."""
    out = {k: job[k] for k in ("id", "status", "summary", "profile", "cards", "actions", "usage", "error",
                               "researchers")} | {"running": is_running(job["id"]), "created": job.get("created")}
    media = images.lookup(catalog.campus_of(job["profile"]), [c["name"] for c in job["cards"]])
    out["cards"] = []
    for c in job["cards"]:
        m = media.get(_norm(c["name"]), {})
        photos, logo = m.get("photos", []), m.get("logo", "")
        # status: also fixes pre-"unverified" jobs; image: photos[0] or logo, for older clients
        out["cards"].append({**c, "status": card_status(c), "photos": photos, "logo": logo,
                             "image": photos[0] if photos else logo, "detail": detail_level(c)})
    return out


def any_running() -> bool:
    with _lock:
        return bool(_running)


def snapshot_usage(job: dict) -> dict[str, Any]:
    return job.get("usage") or {}
