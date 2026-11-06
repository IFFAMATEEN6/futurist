"""Tests for deadline/effort ranking and Coach planning."""
import config
from agents import coach


def opportunity(opp_id, deadline, effort_hours, title=None):
    return {
        "id": opp_id,
        "title": title or f"Opportunity {opp_id}",
        "deadline": deadline,
        "effort_hours": effort_hours,
    }


def match(opp_id, score=70, eligible=True, gaps=None, eligibility_reasons=None):
    return {
        "opportunity_id": opp_id,
        "eligible": eligible,
        "score": score,
        "gaps": gaps or [],
        "eligibility_reasons": eligibility_reasons or [],
    }


def setup_llm_fallback(monkeypatch):
    monkeypatch.setattr(coach.llm, "ask", lambda *args, **kwargs: (None, "no provider"))


def test_ranks_only_eligible_verified_opportunities_and_limits_top_three(monkeypatch):
    monkeypatch.setattr(config, "TODAY", "2026-11-06")
    setup_llm_fallback(monkeypatch)
    opportunities = [
        opportunity("rolling", "rolling", 4),
        opportunity("urgent", "2026-11-10", 8),
        opportunity("later", "2027-01-15", 10),
        opportunity("ineligible", "2026-11-07", 1),
        opportunity("fourth", "2027-02-01", 2),
    ]
    state = {
        "verified": opportunities,
        "matches": [
            match("rolling", 65), match("urgent", 80), match("later", 90),
            match("ineligible", 100, eligible=False), match("fourth", 50),
        ],
        "profile": {"projects": ["class project"]},
    }

    result = coach.run(state)

    ranked = result["plan"]["ranked"]
    assert len(ranked) == 3
    assert [item["rank"] for item in ranked] == [1, 2, 3]
    assert "ineligible" not in [item["opportunity_id"] for item in ranked]
    assert all(item["deadline"] and item["why"] for item in ranked)
    assert result["challenge"] is None


def test_emits_one_challenge_for_close_deadlines_over_weekly_capacity(monkeypatch):
    monkeypatch.setattr(config, "TODAY", "2026-11-06")
    setup_llm_fallback(monkeypatch)
    opportunities = [
        opportunity("a", "2026-11-12", 8, "AI Internship"),
        opportunity("b", "2026-11-15", 7, "Research Scholarship"),
    ]
    state = {
        "verified": opportunities,
        "matches": [match("a"), match("b")],
        "profile": {"weekly_hours": 10},
    }

    result = coach.run(state)

    assert result["challenge"]["ids"] == ["a", "b"]
    assert "15 effort hours combined" in result["challenge"]["reason"]
    assert any(message["type"] == "challenge" for message in result["messages"])
    assert len(result["plan"]["ranked"]) == 2


def test_does_not_challenge_after_the_single_allowed_round(monkeypatch):
    monkeypatch.setattr(config, "TODAY", "2026-11-06")
    setup_llm_fallback(monkeypatch)
    state = {
        "verified": [
            opportunity("a", "2026-11-12", 8),
            opportunity("b", "2026-11-15", 7),
        ],
        "matches": [match("a"), match("b")],
        "profile": {"weekly_hours": 10},
        "round_c": 1,
    }

    result = coach.run(state)

    assert result["challenge"] is None
    assert len(result["plan"]["ranked"]) == 2


def test_does_not_assume_weekly_hours_when_the_profile_omits_them(monkeypatch):
    monkeypatch.setattr(config, "TODAY", "2026-11-06")
    setup_llm_fallback(monkeypatch)
    state = {
        "verified": [
            opportunity("a", "2026-11-12", 8),
            opportunity("b", "2026-11-15", 7),
        ],
        "matches": [match("a"), match("b")],
        "profile": {},
    }

    result = coach.run(state)

    assert result["challenge"] is None
    assert any("Weekly availability was not provided" in message["text"]
               for message in result["messages"])


def test_can_read_weekly_availability_from_student_input(monkeypatch):
    monkeypatch.setattr(config, "TODAY", "2026-11-06")
    setup_llm_fallback(monkeypatch)
    state = {
        "student_input": "I can spend 10 hours per week on applications.",
        "verified": [
            opportunity("a", "2026-11-12", 8),
            opportunity("b", "2026-11-15", 7),
        ],
        "matches": [match("a"), match("b")],
        "profile": {},
    }

    assert coach.run(state)["challenge"]["ids"] == ["a", "b"]


def test_no_eligible_matches_still_returns_useful_plan(monkeypatch):
    setup_llm_fallback(monkeypatch)
    state = {
        "verified": [opportunity("a", "2026-12-01", 8)],
        "matches": [match("a", eligible=False, eligibility_reasons=["Needs year 4+"])],
        "profile": {"year": None, "gpa": None},
    }

    result = coach.run(state)

    assert result["plan"]["ranked"] == []
    assert result["plan"]["weekly_checklist"]
    assert result["plan"]["improvement_tips"]
    assert result["challenge"] is None


def test_uses_valid_llm_checklist_and_tips(monkeypatch):
    monkeypatch.setattr(config, "TODAY", "2026-11-06")
    monkeypatch.setattr(
        coach.llm, "ask",
        lambda *args, **kwargs: ({
            "weekly_checklist": [{"week": 1, "tasks": ["Tailor your resume."]}],
            "improvement_tips": ["Show a relevant project."],
        }, "test-provider"),
    )
    state = {
        "verified": [opportunity("a", "2026-11-20", 5)],
        "matches": [match("a")],
        "profile": {},
    }

    result = coach.run(state)

    assert result["plan"]["weekly_checklist"] == [
        {"week": 1, "tasks": ["Tailor your resume."]}
    ]
    assert result["plan"]["improvement_tips"] == ["Show a relevant project."]
    assert any("test-provider" in message["text"] for message in result["messages"])


def test_invalid_llm_output_uses_safe_code_fallback(monkeypatch):
    monkeypatch.setattr(config, "TODAY", "2026-11-06")
    monkeypatch.setattr(coach.llm, "ask", lambda *args, **kwargs: ({"wrong": []}, "test-provider"))
    state = {
        "verified": [opportunity("a", "2026-11-20", 5)],
        "matches": [match("a")],
        "profile": {},
    }

    result = coach.run(state)

    assert result["plan"]["weekly_checklist"]
    assert result["plan"]["improvement_tips"]
    assert any("code fallback" in message["text"] for message in result["messages"])


def test_missing_state_does_not_crash_and_logs_error(monkeypatch):
    setup_llm_fallback(monkeypatch)

    result = coach.run(None)

    assert result["plan"] == {
        "ranked": [],
        "weekly_checklist": [],
        "improvement_tips": [],
    }
    assert result["challenge"] is None
    assert result["messages"][0]["type"] == "error"
