"""Scout agent. Owner: M1.
"""
import copy
import heapq
import json
import re
from functools import lru_cache

import config
from state import error_msg, make_msg

# --- keyword tables: add a row to support a new type or topic -------------------------
TYPE_KEYWORDS = {
    "internship": ("internship", "internships", "intern"),
    "scholarship": ("scholarship", "scholarships", "fellowship", "fellowships", "grant", "stipend"),
    "hackathon": ("hackathon", "hackathons"),
    "competition": ("competition", "competitions", "contest", "contests"),
    "workshop": ("workshop", "workshops", "bootcamp", "training"),
}
TOPIC_KEYWORDS = {
    "ai": ("ai", "artificial intelligence", "machine learning", "ml", "deep learning", "nlp"),
    "data": ("data", "data science", "analytics", "sql"),
    "web": ("web", "frontend", "backend", "full stack", "html", "react"),
    "security": ("security", "cybersecurity", "cyber"),
    "mobile": ("mobile", "android", "ios", "flutter"),
    "cloud": ("cloud", "aws", "devops"),
    "research": ("research", "phd", "thesis"),
    "software": ("software", "programming", "developer", "engineering"),
}

TYPE_SCORE = 3     # record type matches an interest
TOPIC_SCORE = 2    # per matching topic

_NON_WORD = re.compile(r"[^a-z0-9]+")
_INTERESTS_PART = re.compile(r"interests?\s*[:\-]\s*([^\n]+)", re.IGNORECASE)


# --- text helpers -----------------------------------------------------------------------
def _norm(text: str) -> str:
    """Lowercase, punctuation -> single spaces, padded so ' word ' matches whole words only."""
    return " " + _NON_WORD.sub(" ", str(text).lower()).strip() + " "


def _has(norm_text: str, word: str) -> bool:
    return f" {word} " in norm_text


def _record_text(rec: dict) -> str:
    parts = [rec.get("title", ""), rec.get("description", ""), rec.get("org", "")]
    parts += rec.get("required_skills") or []
    return " ".join(str(p) for p in parts)


# --- dataset access (cached) ------------------------------------------------------------
def build_index(records: list) -> tuple:
    """Prepare records once: a tuple of (record, normalized searchable text)."""
    return tuple((r, _norm(_record_text(r))) for r in records if isinstance(r, dict))


@lru_cache(maxsize=2)
def _read_index(path: str, mtime: float) -> tuple:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("opportunities.json must contain a list of records")
    return build_index(data)


def load_index() -> tuple:
    """Cached read of the dataset. Re-reads only when the file's modified time changes."""
    path = config.OPPORTUNITIES_PATH
    return _read_index(str(path), path.stat().st_mtime)


# --- interests --------------------------------------------------------------------------
def extract_interests(student_input: str, interests_override=None) -> dict:
    """Return {"types": [...], "topics": [...]} found in the student's interests."""
    if interests_override:
        text = " ".join(interests_override)
    else:
        text = student_input or ""
        m = _INTERESTS_PART.search(text)
        if m:                       # use only the interests part, not the skills list
            text = m.group(1)
    norm = _norm(text)
    return {
        "types": [t for t, words in TYPE_KEYWORDS.items() if any(_has(norm, w) for w in words)],
        "topics": [t for t, words in TOPIC_KEYWORDS.items() if any(_has(norm, w) for w in words)],
    }


# --- ranking ----------------------------------------------------------------------------
def _deadline_key(rec: dict):
    """Upcoming deadlines first ('rolling' leads them), then passed ones."""
    deadline = rec.get("deadline", "")
    if deadline == "rolling":
        return (0, "")
    return (1 if deadline < config.TODAY else 0, deadline)


def _score(rec: dict, norm_text: str, interests: dict) -> int:
    score = TYPE_SCORE if rec.get("type") in interests["types"] else 0
    for topic in interests["topics"]:
        if any(_has(norm_text, w) for w in TOPIC_KEYWORDS[topic]):
            score += TOPIC_SCORE
    return score


def _select(index: tuple, interests: dict):
    """Return (picked records, explanation). Top-N by heap: O(n log N)."""
    n = config.MAX_CANDIDATES
    if not interests["types"] and not interests["topics"]:
        picked = heapq.nsmallest(n, (r for r, _ in index), key=_deadline_key)
        return picked, "No interests found, so I picked the opportunities with the nearest deadlines."
    scored = ((_score(r, t, interests), r) for r, t in index)
    best = heapq.nsmallest(n, ((s, r) for s, r in scored if s > 0),
                           key=lambda sr: (-sr[0], _deadline_key(sr[1])))
    note = (f"Matched on types {interests['types'] or 'any'} "
            f"and topics {interests['topics'] or 'any'}.")
    return [r for _, r in best], note


# --- re-check mode (Loop 1) -------------------------------------------------------------
def _recheck(state: dict, index: tuple) -> dict:
    """Re-read only the ids the Verifier doubted, and answer it."""
    by_id = {r.get("id"): r for r, _ in index}
    candidates = list(state.get("candidates", []))
    messages = []
    for opp_id in state.get("recheck", []):
        rec = by_id.get(opp_id)
        if rec is None:
            messages.append(make_msg("scout", "verifier", "response",
                                     f"Could not find {opp_id} in the dataset."))
            continue
        fresh = copy.deepcopy(rec)
        for i, cand in enumerate(candidates):
            if cand.get("id") == opp_id:
                candidates[i] = fresh
                break
        else:
            candidates.append(fresh)
        messages.append(make_msg(
            "scout", "verifier", "response",
            f"Re-checked {opp_id} ({rec.get('title')}): deadline {rec.get('deadline')} "
            f"confirmed in the dataset (last checked {rec.get('last_checked')})."))
    return {"candidates": candidates, "messages": messages}


# --- agent entry point ------------------------------------------------------------------
def run(state: dict) -> dict:
    try:
        index = load_index()
    except Exception as exc:
        return {"candidates": [], "messages": [error_msg("scout", f"Could not load the dataset: {exc}")]}

    try:
        if state.get("recheck"):
            return _recheck(state, index)

        interests = extract_interests(state.get("student_input", ""), state.get("interests_override"))
        picked, note = _select(index, interests)
        picked = copy.deepcopy(picked)      # copies, so no agent can alter the cached dataset

        if not picked:
            return {"candidates": [], "messages": [make_msg(
                "scout", "all", "info", "No opportunities match these interests. " + note)]}
        return {"candidates": picked, "messages": [make_msg(
            "scout", "verifier", "result", f"Found {len(picked)} candidates. {note}")]}
    except Exception as exc:
        return {"candidates": [], "messages": [error_msg("scout", f"Scout failed: {exc}")]}