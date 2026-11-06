"""Profiler agent. Owner: M3. Writes only: profile (+ messages)."""
import re, json

try:
    from llm import call_llm_json   # M4's wrapper; name may differ
except Exception:
    call_llm_json = None

ALIASES = {"ml": "Machine Learning", "machine learning": "Machine Learning",
           "py": "Python", "python": "Python", "html": "HTML", "css": "CSS",
           "sql": "SQL", "js": "JavaScript", "javascript": "JavaScript"}
FIELDS = ["Computer Science", "Software Engineering", "Data Science",
          "Electrical Engineering", "Business", "Pharmacy"]

def _msg(recipient, type_, text):
    return {"sender": "profiler", "recipient": recipient, "type": type_, "text": text}

def _known_skills():
    try:
        with open("data/skill_map.json", encoding="utf-8") as f:
            d = json.load(f)
        return list(d.keys()) if isinstance(d, dict) else []
    except Exception:
        return []

def _norm_skill(s, known):
    low = s.strip().lower()
    if low in ALIASES:
        return ALIASES[low]
    for k in known:
        if k.lower() == low:
            return k
    return s.strip().title()

def _parse(text, known):
    low = text.lower()
    year = None
    m = re.search(r"(first|second|third|fourth|1st|2nd|3rd|4th|\b[1-4]\b)[\s-]*year", low)
    if m:
        w = m.group(1)
        year = {"first": 1, "1st": 1, "second": 2, "2nd": 2,
                "third": 3, "3rd": 3, "fourth": 4, "4th": 4}.get(w)
        if year is None:
            year = int(w)
    gpa = None
    m = re.search(r"gpa[^0-9]{0,10}([0-4](?:\.\d+)?)", low)
    if m:
        gpa = float(m.group(1))
    field = next((f for f in FIELDS if f.lower() in low), None)
    nationality = "Pakistani" if "pakistan" in low else None
    skills = []
    m = re.search(r"skills?\s*[:\-]\s*([^.\n]+)", text, re.I)
    if m:
        for s in re.split(r",|;|\band\b", m.group(1)):
            s = re.sub(r"\(.*?\)", "", s).strip()
            if s:
                skills.append(_norm_skill(s, known))
    interests = []
    m = re.search(r"interested in\s+([^.\n]+)", text, re.I)
    if m:
        interests = [i.strip().lower() for i in re.split(r",|\band\b", m.group(1)) if i.strip()]
    projects = re.findall(r"(?:built|made|created|developed)\s+[^.\n]+", text, re.I)
    nm = re.search(r"I'?m\s+([A-Z][a-z]+)", text)
    return {"name": nm.group(1) if nm else "Student", "year": year, "field": field,
            "gpa": gpa, "nationality": nationality,
            "skills": list(dict.fromkeys(skills)), "interests": interests,
            "projects": projects}

def _score(p):
    score, notes = 0, []
    score += min(len(p["skills"]), 6) * 6
    score += min(len(p["projects"]), 3) * 10
    if p["gpa"] is not None:
        score += int(p["gpa"] / 4.0 * 20)
    else:
        notes.append("GPA missing, score is lower.")
    if p["year"] is not None:
        score += min(p["year"], 4) * 3
    else:
        notes.append("Year missing.")
    if len(p["skills"]) < 3:
        notes.append("Add more skills.")
    if not p["projects"]:
        notes.append("Add at least one project.")
    return min(score, 100), notes

def run(state: dict) -> dict:
    try:
        text = (state.get("student_input") or "").strip()
        if not text:
            return {"profile": {}, "messages": [_msg("all", "error", "Empty input, no profile built.")]}
        known = _known_skills()
        p = _parse(text, known)
        if call_llm_json:
            try:
                out = call_llm_json("Extract year, gpa, field, nationality, skills, "
                                    "interests, projects as JSON from: " + text)
                if isinstance(out, dict):
                    for k in ("year", "gpa", "field", "nationality", "skills", "interests", "projects"):
                        if out.get(k) not in (None, "", []):
                            p[k] = out[k]
                    p["skills"] = [_norm_skill(s, known) for s in p["skills"]]
            except Exception:
                pass
        p["strength_score"], p["strength_notes"] = _score(p)
        msgs = [_msg("all", "result", f"Profile built. Strength {p['strength_score']}/100.")]
        for k in ("year", "gpa"):
            if p[k] is None:
                msgs.append(_msg("matcher", "info", f"{k} unknown, treated as unknown."))
        return {"profile": p, "messages": msgs}
    except Exception as e:
        return {"profile": {}, "messages": [_msg("all", "error", f"Profiler failed: {e}")]}