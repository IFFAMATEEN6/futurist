"""Matcher agent (Member 4).

Reads:  state["profile"], state["verified"], state["challenge"] (from Coach, optional)
Writes: state["matches"] + new messages

All rules are plain code (no LLM), so the Matcher works offline and never raises.

Match object:
  {opportunity_id, eligible, eligibility_reasons, score (0-100), score_reasons, gaps: [{skill, reason}]}
"""
import json
import re
from pathlib import Path

from state import error_msg, make_msg
from domain import normalize_field, normalize_nationality, normalize_skill, number

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SENDER = "matcher"  # lowercase, same as state.OWNED_KEYS

# score weights (sum = 1.0)
W_SKILL = 0.5
W_INTEREST = 0.3
W_STRENGTH = 0.2

CLASH_PENALTY = 15  # points removed from the lower-ranked item in a Coach clash

# short names students often type
SKILL_ALIASES = {
    "ml": "machine learning",
    "dl": "deep learning",
    "js": "javascript",
    "py": "python",
    "dsa": "data structures",
    "ds": "data structures",
    "ui/ux": "ui/ux design",
    "ux": "ui/ux design",
    "aws": "cloud",
    "gcp": "cloud",
    "azure": "cloud",
}

INTEREST_KEYWORDS = {
    "ai": ["ai", "artificial intelligence", "machine learning", "deep learning", "ml", "data"],
    "web": ["web", "html", "css", "javascript", "react", "frontend"],
    "data": ["data", "analysis", "sql", "statistics", "analytics"],
}


# ---------- helpers ----------

def _msg(recipient, mtype, text):
    return make_msg(SENDER, recipient, mtype, text)


def _load_json(name, default):
    try:
        with open(DATA_DIR / name, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _norm(s):
    s = str(s or "").strip().lower()
    return SKILL_ALIASES.get(s, s)


def _num(v):
    return number(v)


def has_skill(profile_skills, required):
    """True if a profile skill covers the required one (case-insensitive, aliases, 'basic X' counts)."""
    req = normalize_skill(required)
    return bool(req) and any(normalize_skill(s) == req for s in profile_skills)


# ---------- eligibility ----------

def assess_eligibility(profile, opp):
    """Returns (eligible, reasons). Reasons list every failed rule and every unknown value."""
    rules = opp.get("eligibility") or {}
    if not isinstance(rules, dict):
        return "ineligible", ["Malformed eligibility rules; this listing cannot be assessed."]
    reasons, eligible = [], True
    if not rules:
        reasons.append("Eligibility rules are not documented; confirm them on the source page.")

    # year
    min_year = _num(rules.get("min_year"))
    year = _num(profile.get("year"))
    if min_year is not None:
        if year is None:
            reasons.append(f"Year unknown in profile (needs year {int(min_year)}+); not checked")
        elif year < min_year:
            eligible = False
            reasons.append(f"Needs year {int(min_year)}+, student is year {int(year)}")

    max_year = _num(rules.get("max_year"))
    if max_year is not None:
        if year is None and min_year is None:
            reasons.append("Year unknown in profile; upper year limit needs confirmation")
        elif year is not None and year > max_year:
            eligible = False
            reasons.append(f"Open up to year {int(max_year)}, student is year {int(year)}")

    # GPA
    min_gpa = _num(rules.get("min_gpa"))
    gpa = _num(profile.get("gpa"))
    if min_gpa is not None and min_gpa > 0:
        if gpa is None:
            reasons.append(f"GPA unknown in profile (needs {min_gpa}+); not checked")
        elif gpa < min_gpa:
            eligible = False
            reasons.append(f"Needs GPA {min_gpa}+, student has {gpa}")

    # field
    fields = [normalize_field(f) for f in (rules.get("fields") or []) if f]
    field = normalize_field(profile.get("field"))
    if fields:
        if not field:
            reasons.append("Field unknown in profile; not checked")
        elif field not in fields and not ("engineering" in fields and field in {
                "electrical engineering", "mechanical engineering", "software engineering"}):
            eligible = False
            reasons.append(f"Open to {', '.join(rules['fields'])}, student is in {profile.get('field')}")

    # nationality
    nats = [normalize_nationality(n) for n in (rules.get("nationalities") or []) if n]
    nat = normalize_nationality(profile.get("nationality"))
    if nats:
        if not nat:
            reasons.append("Nationality unknown in profile; not checked")
        elif nat not in nats:
            eligible = False
            reasons.append(f"Open to {', '.join(rules['nationalities'])} only, student is {profile.get('nationality')}")

    if not eligible:
        return "ineligible", reasons
    if opp.get("eligibility_complete") is False:
        reasons.append("Full program rules are not documented in the catalog; confirm them on the source page.")
    if opp.get("verification_status") == "needs_review":
        reasons.append("Source freshness or deadline details still need review.")
    status = "conditional" if reasons else "eligible"
    return status, reasons or ["Meets all recorded eligibility rules; confirm current rules on the source."]


def check_eligibility(profile, opp):
    """Compatibility helper: only confirmed recorded rules produce True."""
    status, reasons = assess_eligibility(profile, opp)
    return status == "eligible", reasons


# ---------- scoring ----------

def _interest_score(profile, opp):
    interests = [str(i).lower() for i in (profile.get("interests") or []) if i]
    if not interests:
        return 0.5, "No interests given, neutral interest score"

    otype = str(opp.get("type") or "").lower()
    text = " ".join([str(opp.get("title") or ""), str(opp.get("org") or ""), str(opp.get("description") or "")]
                    + [str(s) for s in (opp.get("required_skills") or [])]).lower()

    type_hit = bool(otype) and any(otype in i or otype.rstrip("s") in i for i in interests)
    words = set()
    for i in interests:
        for w in re.findall(r"[a-z+#]+", i):
            if len(w) >= 2 and w not in {"and", "in", "for", "the", "of"} and not (otype and otype.rstrip("s") in w):
                words.add(w)
                words.update(INTEREST_KEYWORDS.get(w, []))
    kw_hit = any(re.search(r"\b" + re.escape(w) + r"\b", text) for w in words)

    if type_hit and kw_hit:
        return 1.0, "Matches interest in type and topic"
    if type_hit:
        return 0.6, f"Matches interest in {otype}s"
    if kw_hit:
        return 0.4, "Topic matches interests, type does not"
    return 0.0, "Does not match stated interests"


def score_match(profile, opp):
    """Returns (score 0-100, reasons, missing_skills)."""
    skills = profile.get("skills") or []
    required = [s for s in (opp.get("required_skills") or []) if s]
    have = [r for r in required if has_skill(skills, r)]
    missing = [r for r in required if r not in have]

    undocumented = not required and opp.get("eligibility_complete") is False
    skill_part = len(have) / len(required) if required else 0.5 if undocumented else 1.0
    interest_part, interest_reason = _interest_score(profile, opp)
    strength = _num(profile.get("strength_score"))
    strength_part = max(0.0, min(strength, 100.0)) / 100 if strength is not None else 0.5

    score = round(100 * (W_SKILL * skill_part + W_INTEREST * interest_part + W_STRENGTH * strength_part))
    reasons = [
        f"Skills: has {len(have)}/{len(required)} required" if required else
        "Skill requirements not documented; used a neutral score. Confirm them on the source." if undocumented else "Skills: none required",
        f"Interest: {interest_reason}",
        f"Profile strength: {int(strength)}/100" if strength is not None else "Profile strength unknown, used 50",
    ]
    return score, reasons, missing


def build_gaps(missing, opp, skill_map):
    gaps = []
    for skill in missing:
        info = next((v for k, v in skill_map.items() if k.lower() == _norm(skill)), None)
        if info:
            reason = (f"Required by {opp.get('title', 'this opportunity')}. Learn: {info.get('learn')} "
                      f"(~{info.get('hours')} h). Start: {info.get('resource')}")
        else:
            reason = f"Required by {opp.get('title', 'this opportunity')}. Not in skill map; look for an introductory course"
        gaps.append({"skill": skill, "reason": reason, "resource": info.get("resource") if info else None,
                     "hours": info.get("hours") if info else None, "learn": info.get("learn") if info else None})
    return gaps


# ---------- Coach challenge ----------

def _challenge_ids(challenge):
    """Accepts a list of ids or a dict with ids under common keys."""
    if not challenge:
        return []
    if isinstance(challenge, (list, tuple)):
        return [str(x) for x in challenge]
    if isinstance(challenge, dict):
        for key in ("ids", "opportunity_ids", "clash", "clashing_ids"):
            if challenge.get(key):
                return [str(x) for x in challenge[key]]
    return []


def apply_challenge(matches, challenge):
    """Keep the best-scoring clashing item, lower the others. Returns (matches, reply_text or None)."""
    ids = _challenge_ids(challenge)
    clashing = [m for m in matches if m["opportunity_id"] in ids and m.get("eligibility_status") != "ineligible"
                and (m.get("eligible") or m.get("eligibility_status") == "conditional")]
    if len(clashing) < 2:
        return matches, ("Received clash challenge but fewer than two of those ids are eligible matches; "
                         "ranking unchanged" if ids else None)

    preferred = challenge.get("preferred_id") if isinstance(challenge, dict) else None
    clashing.sort(key=lambda m: (m["opportunity_id"] != preferred, -m["score"], m["opportunity_id"]))
    keep = clashing[0]
    for m in clashing[1:]:
        m["score"] = max(0, m["score"] - CLASH_PENALTY)
        m["score_reasons"].append(
            f"Deadline clash with {keep['opportunity_id']} (Coach challenge): priority lowered by {CLASH_PENALTY}")
    lowered = ", ".join(m["opportunity_id"] for m in clashing[1:])
    return matches, f"Re-ranked after clash: kept {keep['opportunity_id']} first, lowered {lowered}"


# ---------- agent ----------

def _resolve_opportunities(state):
    """Verified may hold full records or just ids. Look ids up in candidates, then the dataset."""
    verified = state.get("verified") or []
    if all(isinstance(v, dict) for v in verified):
        return verified
    pool = {o.get("id"): o for o in (state.get("candidates") or []) if isinstance(o, dict)}
    if any(not isinstance(v, dict) and v not in pool for v in verified):
        pool.update({o.get("id"): o for o in _load_json("opportunities.json", []) if isinstance(o, dict)})
    out = []
    for v in verified:
        if isinstance(v, dict):
            out.append(v)
        elif v in pool:
            out.append(pool[v])
    return out


def _sort(matches):
    return sorted(matches, key=lambda m: ({"eligible": 0, "conditional": 1, "ineligible": 2}.get(
        m.get("eligibility_status"), 2), -m["score"], m["opportunity_id"]))


def matcher(state):
    messages = []
    try:
        profile = state.get("profile") or {}
        opps = _resolve_opportunities(state)
        skill_map = _load_json("skill_map.json", {})

        if not profile or "profiler" in state.get("failures", []) or not any(
                profile.get(key) for key in ("year", "field", "gpa", "skills", "projects")):
            return {"matches": [], "messages": [_msg("coach", "info",
                    "No usable profile evidence is available. Add your study year, field and named skills before matching.")]}
        if not opps:
            messages.append(_msg("coach", "result", "No verified opportunities to match"))
            return {"matches": [], "messages": messages}

        matches = []
        for opp in opps:
            if not opp.get("id"):
                continue
            status, e_reasons = assess_eligibility(profile, opp)
            eligible = status == "eligible"
            score, s_reasons, missing = score_match(profile, opp)
            matches.append({
                "opportunity_id": opp["id"],
                "eligible": eligible,
                "eligibility_status": status,
                "eligibility_reasons": e_reasons,
                "score": score if status != "ineligible" else 0,
                "score_reasons": s_reasons,
                "gaps": build_gaps(missing, opp, skill_map),
            })
            if any("unknown" in r for r in e_reasons):
                messages.append(_msg("coach", "info", f"{opp['id']}: " + "; ".join(
                    r for r in e_reasons if "unknown" in r)))

        challenge = state.get("challenge")
        if challenge:
            matches, reply = apply_challenge(matches, challenge)
            if reply:
                messages.append(_msg("coach", "response", reply))

        matches = _sort(matches)
        n_ok = sum(m["eligible"] for m in matches)
        conditional = sum(m["eligibility_status"] == "conditional" for m in matches)
        top = ", ".join(f"{m['opportunity_id']} ({m['score']})" for m in matches if m["eligibility_status"] != "ineligible")[:200]
        messages.append(_msg("coach", "result",
                             f"Assessed {len(matches)} listings: {n_ok} meet recorded rules, {conditional} need confirmation."
                             + (f" Strongest fits: {top}. Prioritize with the student's weekly capacity." if top else "")))
        return {"matches": matches, "messages": messages}

    except Exception as e:  # never raise
        messages.append(error_msg(SENDER, f"Matcher failed: {str(e)[:150]}. Returning no matches"))
        return {"matches": [], "messages": messages}


# alias so graph.py can use either name
agent = matcher
run = matcher  # entry point used by graph.py
