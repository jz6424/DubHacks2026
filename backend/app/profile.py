"""The student's answers from onboarding (spec Phase 1)."""
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field

INTERESTS = [
    "Academic/professional (pre-med, pre-law, business, engineering, CS)",
    "Tech/hackathons/building projects",
    "Cultural/identity-based communities",
    "Arts/music/dance/theater/film",
    "Sports/outdoor/recreation",
    "Service/volunteering/activism",
    "Faith/spiritual",
    "Media/writing/publications",
    "Gaming/hobbies/special interests",
    "Social/Greek life",
    "Research/competitive teams (robotics, case competitions, Model UN)",
]
IDENTITY_INTEREST = "Cultural/identity-based communities"
GOALS = ["make friends", "build my résumé", "learn a skill", "find community", "compete", "give back", "have fun",
         "find leadership roles"]
COMMITMENT_LABEL = {"casual": "🌱 Casual (under 2 hrs/wk)", "regular": "🌿 Regular (2–5 hrs/wk)",
                    "committed": "🌳 Committed (5–10 hrs/wk)", "all_in": "🔥 All-in (10+ hrs/wk)"}
COMMITMENT_MAX_HOURS = {"casual": 2, "regular": 5, "committed": 10, "all_in": 40}
BUDGET_LABEL = {"free": "free only", "under_50": "under $50 per quarter", "flexible": "flexible"}


class Profile(BaseModel):
    campus: Literal["seattle", "bothell", "tacoma"] | None = None
    year: str | None = None
    major: str | None = None
    interests: list[str] = Field(default_factory=list)
    commitment: Literal["casual", "regular", "committed", "all_in"] | None = None
    goals: list[str] = Field(default_factory=list, max_length=3)
    availability: list[str] = Field(default_factory=list)  # e.g. "weekday evenings", "weekends"
    budget: Literal["free", "under_50", "flexible"] | None = None
    experience: Literal["beginners_only", "open_to_selective"] | None = None
    avoid: str | None = Field(default=None, max_length=300)

    def key(self) -> str:
        """Stable hash: identical answers reuse the same research (and make demos instant)."""
        return hashlib.sha256(json.dumps(self.model_dump(), sort_keys=True).encode()).hexdigest()[:16]

    def identity_opt_in(self) -> bool:
        return IDENTITY_INTEREST in self.interests

    def summary(self) -> str:
        """2-3 line recap shown before swiping (spec: summarize and confirm)."""
        who = " ".join(x for x in [(self.year or "").strip(), (self.major or "").strip()] if x) or "Student"
        campus = f"UW {self.campus.capitalize()}" if self.campus else "UW (campus not specified)"
        line1 = f"{who} at {campus}."
        into = ", ".join(i.split(" (")[0] for i in self.interests) or "open to anything"
        line2 = f"Into: {into}. Wants to {', '.join(self.goals) or 'explore'}."
        bits = []
        if self.commitment:
            bits.append(COMMITMENT_LABEL[self.commitment])
        if self.availability:
            bits.append("free " + ", ".join(self.availability))
        if self.budget:
            bits.append("dues: " + BUDGET_LABEL[self.budget])
        if self.experience:
            bits.append("beginner-friendly only" if self.experience == "beginners_only" else "open to selective clubs")
        if self.avoid:
            bits.append(f"avoid: {self.avoid}")
        return "\n".join([line1, line2, " · ".join(bits)]) if bits else "\n".join([line1, line2])
