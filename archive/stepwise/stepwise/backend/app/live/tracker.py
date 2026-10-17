"""Step state machine. Pure logic, no I/O — easy to unit test.

States per step: pending -> active -> (verifying) -> done | skipped
Advance rule: `need` consecutive positive checks with conf >= thresh, OR manual.
Hysteresis keeps a single lucky frame from checking things off.
"""
from dataclasses import dataclass, field
from ..models import Plan, CheckResult


@dataclass
class Tracker:
    plan: Plan
    current: int = 0
    need: int = 2
    thresh: float = 0.7
    streak: int = 0
    status: dict[int, str] = field(default_factory=dict)   # idx -> done|skipped
    last_hint: str = ""

    def on_check(self, r: CheckResult) -> list[dict]:
        """Feed a verifier result; returns events to push to the UI."""
        events = [{"type": "check", **r.model_dump()}]
        if r.step_index != self.current:
            # lookahead hit: user did the NEXT step already (common — people skip ahead)
            if r.step_index == self.current + 1 and r.done and r.confidence >= 0.85:
                events += self.complete(self.current, how="inferred")
            return events
        self.streak = self.streak + 1 if (r.done and r.confidence >= self.thresh) else 0
        if r.hint and r.hint != self.last_hint:
            self.last_hint = r.hint
            events.append({"type": "hint", "text": r.hint})
        if self.streak >= self.need:
            events += self.complete(self.current, how="vision")
        elif self.streak == 1:
            events.append({"type": "verifying", "step": self.current})   # UI: ring fills
        return events

    def complete(self, idx: int, how: str) -> list[dict]:
        self.status[idx] = "done" if how != "skip" else "skipped"
        self.current, self.streak, self.last_hint = idx + 1, 0, ""
        ev = [{"type": "step_done", "step": idx, "how": how}]
        if self.current >= len(self.plan.steps):
            ev.append({"type": "finished"})
        else:
            ev.append({"type": "step_active", "step": self.current})
        return ev

    def manual(self, action: str) -> list[dict]:
        if action == "next":
            return self.complete(self.current, how="manual")
        if action == "skip":
            return self.complete(self.current, how="skip")
        if action == "back" and self.current > 0:
            self.current -= 1
            self.status.pop(self.current, None)
            return [{"type": "step_active", "step": self.current}]
        return []
