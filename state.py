"""Shared contract. Owner: M1. """
import operator
from datetime import datetime
from typing import Annotated, Optional, TypedDict
from uuid import uuid4

import config

OPPORTUNITY_TYPES = ("internship", "scholarship", "hackathon", "competition", "workshop")
MSG_TYPES = ("info", "result", "challenge", "response", "reject", "error")

# Single source of truth: the state keys each agent may write ("messages" is always allowed).
# Adding a new agent later = add one line here and one module in agents/.
OWNED_KEYS = {
    "scout": frozenset({"candidates", "recheck_evidence"}),
    "profiler": frozenset({"profile"}),
    "verifier": frozenset({"verified", "rejected", "recheck"}),
    "matcher": frozenset({"matches"}),
    "coach": frozenset({"plan", "challenge"}),
}
AGENT_NAMES = tuple(OWNED_KEYS)


class Msg(TypedDict):
    sender: str      # an agent name or "system"
    recipient: str   # an agent name or "all"
    type: str        # one of MSG_TYPES
    text: str
    ts: str          # ISO time


class Opportunity(TypedDict):
    id: str                  # "opp_001"
    title: str
    org: str
    type: str                # one of OPPORTUNITY_TYPES
    deadline: str            # "YYYY-MM-DD" or "rolling"
    eligibility: dict        # min_year, max_year, min_gpa, fields[], nationalities[]
    required_skills: list
    effort_hours: int
    application_fee: bool
    source_url: str          # official page only
    last_checked: str        # "YYYY-MM-DD"
    description: str
    planted: bool            # True only for the two test listings


class Profile(TypedDict):
    name: str
    year: Optional[int]
    field: Optional[str]
    gpa: Optional[float]
    nationality: Optional[str]
    skills: list
    interests: list
    projects: list
    strength_score: int      # 0-100
    strength_notes: list
    missing_fields: list
    weekly_hours: Optional[float]


class Match(TypedDict):
    opportunity_id: str
    eligible: bool
    eligibility_status: str  # eligible, conditional or ineligible
    eligibility_reasons: list
    score: int               # 0-100
    score_reasons: list
    gaps: list               # [{"skill": "...", "reason": "..."}]


class Plan(TypedDict):
    ranked: list             # [{"opportunity_id","rank","deadline","why","effort_hours"}]
    weekly_checklist: list   # [{"week": 1, "tasks": ["..."]}]
    improvement_tips: list
    deferred: list
    weekly_hours: Optional[float]
    planning_date: str
    total_hours: float


class OpportunityState(TypedDict):
    run_id: str
    run_date: str
    student_input: str                       # UI
    interests_override: list                 # UI (optional form field)
    opportunity_types: list
    weekly_hours: float
    use_llm: bool
    offline: bool
    recheck_evidence: dict
    failures: Annotated[list, operator.add]
    profile: dict                            # Profiler
    candidates: list                         # Scout
    verified: list                           # Verifier
    rejected: list                           # Verifier: [(Opportunity, reason)]
    recheck: list                            # Verifier -> Scout: ids to re-check
    matches: list                            # Matcher
    challenge: Optional[dict]                # Coach -> Matcher: {"ids": [...], "reason": "..."}
    plan: dict                               # Coach
    round_v: int                             # graph: Verifier loop counter
    round_c: int                             # graph: Coach loop counter
    messages: Annotated[list, operator.add]  # everyone: append-only log


def make_msg(sender: str, recipient: str, type: str, text: str) -> Msg:
    """Build one message for the shared log."""
    return {"sender": sender, "recipient": recipient, "type": type, "text": text,
            "ts": datetime.now().isoformat(timespec="seconds")}


def error_msg(sender: str, text: str) -> Msg:
    """Shortcut for an error message addressed to everyone."""
    return make_msg(sender, "all", "error", text)


def new_state(student_input: str, interests_override: Optional[list] = None, *,
              weekly_hours=10, opportunity_types=None, use_llm=False) -> OpportunityState:
    """Initial state for one run. Every key exists, so agents can read state[...] safely."""
    return {
        "run_id": uuid4().hex,
        "run_date": config.TODAY,
        "student_input": student_input,
        "interests_override": list(interests_override or []),
        "opportunity_types": list(opportunity_types or []),
        "weekly_hours": weekly_hours,
        "use_llm": bool(use_llm),
        "offline": not bool(use_llm),
        "recheck_evidence": {},
        "failures": [],
        "profile": {},
        "candidates": [],
        "verified": [],
        "rejected": [],
        "recheck": [],
        "matches": [],
        "challenge": None,
        "plan": {},
        "round_v": 0,
        "round_c": 0,
        "messages": [make_msg("system", "all", "info", "Run started")],
    }
