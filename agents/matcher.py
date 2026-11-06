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

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SENDER = "Matcher"

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
    return {"sender": SENDER, "recipient": recipient, "type": mtype, "text": text}


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
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def has_skill(profile_skills, required):
    """True if a profile skill covers the required one (case-insensitive, aliases, 'basic X' counts)."""
    req = _norm(required)
    for s in profile_skills:
        ps = _norm(s)
        if ps == req or req in ps or (len(ps) > 2 and ps in req):
            return True
    return False


# ---------- eligibility ----------

def check_eligibility(profile, opp):
    """Returns (eligible, reasons). Reasons list every failed rule and every unknown value."""
    rules = opp.get("eligibility") or {}
    reasons, eligible = [], True

    # year
    min_year = _num(rules.get("min_year"))
    year = _num(profile.get("year"))
    if min_year is not None:
        if year is None:
            reasons.append(f"Year unknown in profile (needs year {int(min_year)}+); not checked")
        elif year < min_year:
            eligible = False
            reasons.append(f"Needs year {int(min_year)}+, student is year {int(year)}")

    # GPA
    min_gpa = _num(rules.get("min_gpa"))
    gpa = _num(profile.get("gpa"))
    if min_gpa is not None:
        if gpa is None:
            reasons.append(f"GPA unknown in profile (needs {min_gpa}+); not checked")
        elif gpa < min_gpa:
            eligible = False
            reasons.append(f"Needs GPA {min_gpa}+, student has {gpa}")

    # field
    fields = [f.lower().strip() for f in (rules.get("fields") or []) if f]
    field = str(profile.get("field") or "").lower().strip()
    if fields:
        if not field:
            reasons.append("Field unknown in profile; not checked")
        elif not any(f in field or field in f for f in fields):
            eligible = False
            reasons.append(f"Open to {', '.join(rules['fields'])}, student is in {profile.get('field')}")

    # nationality
    nats = [n.lower().strip() for n in (rules.get("nationalities") or []) if n]
    nat = str(profile.get("nationality") or "").lower().strip()
    if nats:
        if not nat:
            reasons.append("Nationality unknown in profile; not checked")
        elif nat not in nats:
            eligible = False
            reasons.append(f"Open to {', '.join(rules['nationalities'])} only, student is {profile.get('nationality')}")

    if eligible and not reasons:
        reasons.append("Meets all eligibility rules")
    return eligible, reasons


# ---------- scoring ----------

def _interest_score(profile, opp):
    interests = [str(i).lower() for i in (profile.get("interests") or []) if i]
    if not interests:
        return 0.5, "No interests given, neutral interest score"

    otype = str(opp.get("type") or "").lower()
    text = " ".join([str(opp.get("title") or ""), str(opp.get("org") or "")]
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

    skill_part = len(have) / len(required) if required else 1.0
    interest_part, interest_reason = _interest_score(profile, opp)
    strength = _num(profile.get("strength_score"))
    strength_part = max(0.0, min(strength, 100.0)) / 100 if strength is not None else 0.5

    score = round(100 * (W_SKILL * skill_part + W_INTEREST * interest_part + W_STRENGTH * strength_part))
    reasons = [
        f"Skills: has {len(have)}/{len(required)} required" if required else "Skills: none required",
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
        gaps.append({"skill": skill, "reason": reason})
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
    clashing = [m for m in matches if m["opportunity_id"] in ids and m["eligible"]]
    if len(clashing) < 2:
        return matches, ("Received clash challenge but fewer than two of those ids are eligible matches; "
                         "ranking unchanged" if ids else None)

    clashing.sort(key=lambda m: m["score"], reverse=True)
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
    return sorted(matches, key=lambda m: (not m["eligible"], -m["score"]))


def matcher(state):
    messages = []
    try:
        profile = state.get("profile") or {}
        opps = _resolve_opportunities(state)
        skill_map = _load_json("skill_map.json", {})

        if not profile:
            messages.append(_msg("Coach", "info", "No profile available; matching with unknown values"))
        if not opps:
            messages.append(_msg("Coach", "result", "No verified opportunities to match"))
            return {"matches": [], "messages": messages}

        matches = []
        for opp in opps:
            if not opp.get("id"):
                continue
            eligible, e_reasons = check_eligibility(profile, opp)
            score, s_reasons, missing = score_match(profile, opp)
            matches.append({
                "opportunity_id": opp["id"],
                "eligible": eligible,
                "eligibility_reasons": e_reasons,
                "score": score if eligible else 0,
                "score_reasons": s_reasons,
                "gaps": build_gaps(missing, opp, skill_map),
            })
            if any("unknown" in r for r in e_reasons):
                messages.append(_msg("Coach", "info", f"{opp['id']}: " + "; ".join(
                    r for r in e_reasons if "unknown" in r)))

        challenge = state.get("challenge")
        if challenge:
            matches, reply = apply_challenge(matches, challenge)
            if reply:
                messages.append(_msg("Coach", "response", reply))

        matches = _sort(matches)
        n_ok = sum(m["eligible"] for m in matches)
        top = ", ".join(f"{m['opportunity_id']} ({m['score']})" for m in matches if m["eligible"])[:200]
        messages.append(_msg("Coach", "result",
                             f"{n_ok} of {len(matches)} verified opportunities are eligible"
                             + (f". Top: {top}" if n_ok else "")))
        return {"matches": matches, "messages": messages}

    except Exception as e:  # never raise
        messages.append(_msg("Coach", "error", f"Matcher failed: {str(e)[:150]}. Returning no matches"))
        return {"matches": [], "messages": messages}


# alias so graph.py can use either name
agent = matcher