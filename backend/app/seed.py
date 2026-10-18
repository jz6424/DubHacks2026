"""Fill the club catalog ahead of time, so students mostly get clubs that are already verified (no web search) instead
of paying for research on first use. Researches each interest area with a permissive generic profile until the
catalog has `--per-interest` fresh clubs tagged with it, then fetches club photos. Stops starting new work once
`--budget` dollars are spent. This spend is not counted toward the public site's daily budget (limits.py).

    python -m app.seed --dry-run                      show catalog coverage per interest, spend nothing
    python -m app.seed --budget 30 [--per-interest 15] [--campus seattle] [--interest "Sports"...]
    python -m app.seed import FILE.json [...] [--campus seattle]
        merge club cards researched elsewhere (same card JSON as add_club_card, a JSON array per file) into the
        catalog, through the same quality checks; no API calls. Then fetch photos: python -m app.images backfill

Seeded and imported clubs never expire from the catalog.
"""
import argparse
import json
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

from . import catalog, claude, images
from .jobs import thin_card, vet_card
from .profile import INTERESTS

RUN_TARGET = 8  # clubs per research run (one researcher's worth of searching)
RUNS_PER_INTEREST = 3
RUN_RESERVE_USD = 2.0  # don't start a run unless this much budget is left


def coverage(campus: str, interest: str) -> list[dict]:
    return [c for c in catalog.known(campus, [interest], identity_ok=True, limit=500) if not thin_card(c)]


def seed(campus: str, interests: list[str], per_interest: int, budget: float) -> None:
    lock = threading.Lock()
    spent = [0.0]
    seen = {catalog.norm(c["name"]) for i in INTERESTS for c in coverage(campus, i)}
    pics = ThreadPoolExecutor(2)

    def left() -> float:
        with lock:
            return budget - spent[0]

    def one_interest(interest: str) -> str:
        short = interest.split(" (")[0]
        added = 0
        for run in range(RUNS_PER_INTEREST):
            have = coverage(campus, interest)
            need = per_interest - len(have)
            if need <= 0:
                break
            if left() < RUN_RESERVE_USD:
                return f"{short}: stopped, budget used up ({len(have)} clubs)"
            target, count = min(RUN_TARGET, need), [0]

            def add_card(card: dict) -> str:
                if count[0] >= target:
                    return "Not added: that's your target. Stop now and reply with one short sentence."
                card, why = vet_card(card)
                if why:
                    return why
                key = catalog.norm(card["name"])
                with lock:
                    if key in seen:
                        return f"Duplicate: {card['name']} is already in the catalog. Pick a different club."
                    seen.add(key)
                catalog.upsert(campus, card, seeded=True)
                pics.submit(images.ensure, campus, card)
                count[0] += 1
                return f"Saved ({target - count[0]} more to reach your target)."

            usage = claude.Usage()
            profile = {"campus": campus, "interests": [interest], "commitment": None, "goals": [],
                       "availability": [], "budget": "flexible", "experience": "open_to_selective",
                       "note": "Catalog seeding: no single student. Find a broad, representative mix of active clubs "
                               "for this interest area, from casual to competitive; fit_reason can describe who it "
                               "suits."}
            try:
                outcome = claude.research(profile, [interest], target, 0, add_card=add_card,
                                          on_action=lambda _: None, usage=usage, should_stop=lambda: left() <= 0,
                                          avoid=sorted(c["name"] for c in have)[:150])
            except Exception as e:  # noqa: BLE001 - one failed run shouldn't stop the others
                traceback.print_exc()
                outcome = f"error {type(e).__name__}"
            with lock:
                spent[0] += usage.dollars()
            added += count[0]
            print(f"  {short} run {run + 1}: +{count[0]} clubs, ${usage.dollars():.2f} ({outcome}); "
                  f"total ${spent[0]:.2f}", flush=True)
            if count[0] == 0:
                break  # nothing new found: more runs won't help
        return f"{short}: +{added} → {len(coverage(campus, interest))} clubs"

    with ThreadPoolExecutor(3) as ex:
        results = list(ex.map(one_interest, interests))
    print("\nFetching club photos...", flush=True)
    pics.shutdown(wait=True)
    print("\n" + "\n".join(results))
    print(f"\nSpent about ${spent[0]:.2f} of ${budget:.2f}. Catalog: {catalog.stats()}")


REQUIRED = ("club_id", "name", "category", "description", "commitment", "dues", "meeting_schedule", "join_type",
            "status", "last_active", "links", "application", "sources", "interest_areas")


def import_files(paths: list[str], campus: str) -> None:
    """Merge researched cards into the catalog (seeded: never expire). Skips malformed and thin cards, says why."""
    added, skipped = 0, []
    for path in paths:
        cards = json.load(open(path))
        if not isinstance(cards, list):
            sys.exit(f"{path}: expected a JSON array of cards")
        for raw in cards:
            name = str(raw.get("name", "?")) if isinstance(raw, dict) else "?"
            missing = [k for k in REQUIRED if not isinstance(raw, dict) or k not in raw]
            bad_tags = [t for t in (raw.get("interest_areas") or []) if t not in INTERESTS] if not missing else []
            if missing or bad_tags or not raw.get("interest_areas"):
                skipped.append(f"{name}: missing {missing}" if missing else f"{name}: bad interest_areas {bad_tags}")
                continue
            card, why = vet_card(raw)
            if why:
                skipped.append(f"{name}: {why}")
                continue
            catalog.upsert(campus, card, seeded=True)
            added += 1
            print(f"  + {card['name']}  [{card['status']}]  {', '.join(t.split(' (')[0] for t in card['interest_areas'])}")
    print(f"\nImported {added} clubs into {campus}; skipped {len(skipped)}.")
    for s in skipped:
        print(f"  - {s[:160]}")
    print(f"Catalog: {catalog.stats()}. Next: python -m app.images backfill")


def main() -> None:
    if sys.argv[1:2] == ["import"]:
        args = sys.argv[2:]
        campus = "seattle"
        if "--campus" in args:
            i = args.index("--campus")
            campus, args = args[i + 1], args[:i] + args[i + 2:]
        if not args:
            sys.exit("usage: python -m app.seed import FILE.json [...] [--campus seattle]")
        import_files(args, campus)
        return
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--budget", type=float, help="dollars to spend at most (required unless --dry-run)")
    ap.add_argument("--per-interest", type=int, default=15)
    ap.add_argument("--campus", default="seattle", choices=["seattle", "bothell", "tacoma"])
    ap.add_argument("--interest", action="append", help="limit to interests starting with this text (repeatable)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    chosen = [i for i in INTERESTS if not a.interest or any(i.lower().startswith(x.lower()) for x in a.interest)]
    total_need = 0
    for i in chosen:
        n = len(coverage(a.campus, i))
        total_need += max(0, a.per_interest - n)
        print(f"{n:4d} / {a.per_interest}  {i}")
    print(f"\nAbout {total_need} clubs to find; roughly ${total_need * 0.3:.0f} at ~$0.30 per new club (an estimate).")
    if a.dry_run:
        return
    if a.budget is None:
        ap.error("--budget is required (dollars), so a seeding run can't spend more than you meant")
    seed(a.campus, chosen, a.per_interest, a.budget)


if __name__ == "__main__":
    main()
