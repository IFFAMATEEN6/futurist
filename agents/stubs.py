"""Stub agents with FAKE data. Owner: M1.
"""
from state import make_msg

FAKE_RECORDS = [
    {"id": "stub_001", "title": "[STUB] AI Intern", "org": "Stub Org", "type": "internship",
     "deadline": "2026-12-10", "eligibility": {"min_year": 3, "min_gpa": 3.0, "fields": [], "nationalities": []},
     "required_skills": ["Python"], "effort_hours": 6, "application_fee": False,
     "source_url": "https://example.com/stub_001", "last_checked": "2026-11-05",
     "description": "Fake record for testing.", "planted": False},
    {"id": "stub_002", "title": "[STUB] Merit Scholarship", "org": "Stub Foundation", "type": "scholarship",
     "deadline": "2026-12-12", "eligibility": {"min_year": 2, "min_gpa": 3.0, "fields": [], "nationalities": []},
     "required_skills": [], "effort_hours": 5, "application_fee": False,
     "source_url": "https://example.com/stub_002", "last_checked": "2026-11-05",
     "description": "Fake record for testing.", "planted": False},
]


def scout(state: dict) -> dict:
    if state.get("recheck"):
        return {"candidates": state.get("candidates", []), "messages": [make_msg(
            "scout", "verifier", "response", "Re-checked, deadline confirmed (stub).")]}
    return {"candidates": [dict(r) for r in FAKE_RECORDS], "messages": [make_msg(
        "scout", "verifier", "result", f"Found {len(FAKE_RECORDS)} candidates (stub).")]}


def profiler(state: dict) -> dict:
    profile = {"name": "Student A", "year": 3, "field": "Computer Science", "gpa": 3.3,
               "nationality": "", "skills": ["Python", "machine learning", "HTML"],
               "interests": ["AI internships", "scholarships"], "projects": ["class project"],
               "strength_score": 60, "strength_notes": ["stub profile"]}
    return {"profile": profile, "messages": [make_msg(
        "profiler", "all", "result", "Profile built (stub). Strength score 60/100.")]}


def verifier(state: dict) -> dict:
    candidates = state.get("candidates", [])
    recheck = []
    messages = [make_msg("verifier", "matcher", "result", f"Verified {len(candidates)} listings (stub).")]
    if state.get("round_v", 0) == 0 and candidates:          # triggers Loop 1
        recheck = [candidates[0]["id"]]
        messages.append(make_msg("verifier", "scout", "challenge",
                                 f"Please re-check the deadline of {recheck[0]} (stub)."))
    return {"verified": candidates, "rejected": [], "recheck": recheck, "messages": messages}


def matcher(state: dict) -> dict:
    verified = state.get("verified", [])
    matches = [{"opportunity_id": o["id"], "eligible": True, "eligibility_reasons": [],
                "score": 80 - i * 5, "score_reasons": ["stub"], "gaps": []}
               for i, o in enumerate(verified)]
    if state.get("challenge"):                                # reply to Loop 2
        matches.reverse()
        msg = make_msg("matcher", "coach", "response", "Re-ranked after your challenge (stub).")
    else:
        msg = make_msg("matcher", "coach", "result", f"{len(matches)} eligible matches (stub).")
    return {"matches": matches, "messages": [msg]}


def coach(state: dict) -> dict:
    matches = state.get("matches", [])
    by_id = {o["id"]: o for o in state.get("verified", [])}
    ranked = [{"opportunity_id": m["opportunity_id"], "rank": i + 1,
               "deadline": by_id.get(m["opportunity_id"], {}).get("deadline", ""), "why": "stub",
               "effort_hours": by_id.get(m["opportunity_id"], {}).get("effort_hours", 0)}
              for i, m in enumerate(matches[:3])]
    plan = {"ranked": ranked, "weekly_checklist": [{"week": 1, "tasks": ["stub task"]}],
            "improvement_tips": ["stub tip"]}
    challenge, messages = None, []
    if state.get("round_c", 0) == 0 and len(matches) >= 2:   # triggers Loop 2
        challenge = {"ids": [matches[0]["opportunity_id"], matches[1]["opportunity_id"]],
                     "reason": "Two deadlines clash (stub)."}
        messages.append(make_msg("coach", "matcher", "challenge", challenge["reason"]))
    else:
        messages.append(make_msg("coach", "all", "result", "Final plan ready (stub)."))
    return {"plan": plan, "challenge": challenge, "messages": messages}