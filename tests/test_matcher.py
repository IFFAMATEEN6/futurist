"""Tests for the Matcher agent."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import llm  # noqa: E402
from agents.matcher import check_eligibility, has_skill, matcher  # noqa: E402

STUDENT_A = {
    "name": "Student A", "year": 3, "field": "Computer Science", "gpa": 3.3,
    "nationality": "Pakistani", "skills": ["Python", "basic machine learning", "HTML"],
    "interests": ["AI internships", "scholarships"], "projects": ["class project"],
    "strength_score": 60,
}


def opp(id_, **elig):
    base = {"min_year": None, "min_gpa": None, "fields": [], "nationalities": []}
    base.update(elig)
    return {
        "id": id_, "title": "AI Research Intern", "org": "Org", "type": "internship",
        "deadline": "2026-12-15", "eligibility": base,
        "required_skills": ["Python", "Machine Learning", "SQL"], "effort_hours": 6,
        "application_fee": False, "source_url": "https://x.org", "last_checked": "2026-11-05",
        "planted": False,
    }


# ---------- each eligibility rule passes and fails ----------

def test_year_pass_and_fail():
    assert check_eligibility(STUDENT_A, opp("a", min_year=3))[0] is True
    ok, reasons = check_eligibility(STUDENT_A, opp("a", min_year=4))
    assert ok is False and any("year" in r.lower() for r in reasons)


def test_gpa_pass_and_fail():
    assert check_eligibility(STUDENT_A, opp("a", min_gpa=3.0))[0] is True
    ok, reasons = check_eligibility(STUDENT_A, opp("a", min_gpa=3.5))
    assert ok is False and any("GPA" in r for r in reasons)


def test_field_pass_and_fail():
    assert check_eligibility(STUDENT_A, opp("a", fields=["computer science"]))[0] is True
    ok, reasons = check_eligibility(STUDENT_A, opp("a", fields=["Medicine"]))
    assert ok is False and any("Medicine" in r for r in reasons)


def test_nationality_pass_and_fail():
    assert check_eligibility(STUDENT_A, opp("a", nationalities=["Pakistani"]))[0] is True
    ok, reasons = check_eligibility(STUDENT_A, opp("a", nationalities=["American"]))
    assert ok is False and any("American" in r for r in reasons)


def test_every_failed_rule_has_a_reason():
    ok, reasons = check_eligibility(STUDENT_A, opp("a", min_year=4, min_gpa=3.9, fields=["Law"]))
    assert ok is False and len(reasons) == 3


def test_missing_gpa_and_year_are_unknown_not_failed():
    p = dict(STUDENT_A, gpa=None, year=None)
    ok, reasons = check_eligibility(p, opp("a", min_year=3, min_gpa=3.0))
    assert ok is True
    assert sum("unknown" in r for r in reasons) == 2


# ---------- skills, score, gaps ----------

def test_skill_matching_is_loose():
    assert has_skill(["basic machine learning"], "Machine Learning")
    assert has_skill(["ML"], "Machine Learning")
    assert not has_skill(["HTML"], "SQL")


def test_score_range_and_gaps():
    out = matcher({"profile": STUDENT_A, "verified": [opp("a")]})
    m = out["matches"][0]
    assert 0 <= m["score"] <= 100
    assert [g["skill"] for g in m["gaps"]] == ["SQL"]
    assert "sqlbolt" in m["gaps"][0]["reason"]


def test_ineligible_sorted_last():
    out = matcher({"profile": STUDENT_A, "verified": [opp("bad", min_gpa=3.9), opp("good")]})
    assert out["matches"][0]["opportunity_id"] == "good"
    assert out["matches"][1]["eligible"] is False


def test_verified_as_ids_uses_candidates():
    o = opp("x1")
    out = matcher({"profile": STUDENT_A, "verified": ["x1"], "candidates": [o]})
    assert out["matches"][0]["opportunity_id"] == "x1"


# ---------- Coach challenge ----------

def test_challenge_reranks_once():
    a, b = opp("a"), opp("b")
    b["required_skills"] = ["Python"]          # b scores higher
    out = matcher({"profile": STUDENT_A, "verified": [a, b],
                   "challenge": {"ids": ["a", "b"], "text": "deadlines clash"}})
    responses = [m for m in out["messages"] if m["type"] == "response"]
    assert len(responses) == 1
    assert out["matches"][0]["opportunity_id"] == "b"
    assert any("clash" in r for r in out["matches"][1]["score_reasons"])


# ---------- never crashes ----------

def test_empty_and_bad_state_do_not_crash():
    assert matcher({})["matches"] == []
    assert matcher({"profile": None, "verified": None})["matches"] == []
    out = matcher({"profile": STUDENT_A, "verified": [{"id": "z", "eligibility": "broken"}]})
    assert isinstance(out["matches"], list)
    assert all(set(m) >= {"sender", "recipient", "type", "text"} for m in out["messages"])


# ---------- LLM fallback ----------

def test_llm_falls_back_to_next_provider(monkeypatch):
    def fail(*a):
        raise llm.ProviderError("down")
    monkeypatch.setattr(llm, "PROVIDERS", [("p1", fail), ("p2", lambda *a: '{"ok": true}')])
    result, note = llm.ask("x", want_json=True)
    assert result == {"ok": True} and note == "p2"


def test_llm_all_fail_returns_none(monkeypatch):
    def fail(*a):
        raise llm.ProviderError("down")
    def limited(*a):
        raise llm.RateLimitError("429")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    monkeypatch.setattr(llm, "PROVIDERS", [("p1", limited), ("p2", fail)])
    result, note = llm.ask("x")
    assert result is None and "p1: rate limited" in note