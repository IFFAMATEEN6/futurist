"""Real-agent integration tests: no obsolete imports, skips, provider calls or stubs."""
from datetime import date
import json

import config
import graph
from domain import canonical_url

STUDENT_A = """Name: Ahmed Ali
Year: 3
Field: Computer Science
GPA: 3.3
Nationality: Pakistani
Skills: Python, basic machine learning, HTML
Projects: Student grade tracker
Interests: AI internships, scholarships
"""


def test_real_pipeline_returns_grounded_plan_without_stub_agents():
    assert set(graph.agent_status().values()) == {"real"}
    final = graph.run(STUDENT_A, weekly_hours=10)
    assert final["failures"] == []
    assert final["profile"]["year"] == 3
    assert final["profile"]["interests"] == ["AI internships", "scholarships"]
    assert final["plan"]["ranked"]
    assert "stub" not in json.dumps(final).lower()
    matches = {match["opportunity_id"]: match for match in final["matches"]}
    for item in final["plan"]["ranked"]:
        assert matches[item["opportunity_id"]]["eligibility_status"] in ("eligible", "conditional")
        assert item["source_url"].startswith("https://")


def test_both_planted_listings_are_rejected_in_real_flow():
    final = graph.run(STUDENT_A)
    rejected = {opp["id"]: reason for opp, reason in final["rejected"]}
    assert "passed" in rejected["opp_m2_planted_expired"]
    assert "fee" in rejected["opp_m2_planted_fee"]


def test_real_verified_records_are_safe_deduplicated_and_not_expired():
    final = graph.run(STUDENT_A)
    assert final["verified"]
    sources = [canonical_url(opp["source_url"]) for opp in final["verified"]]
    assert len(sources) == len(set(sources))
    for opp in final["verified"]:
        assert opp["application_fee"] is False
        assert opp["deadline"] == "rolling" or date.fromisoformat(opp["deadline"]) >= date.fromisoformat(config.TODAY)
        assert opp["source_checked_live"] is False


def test_real_plan_respects_capacity_and_finishes_before_deadlines():
    final = graph.run(STUDENT_A, weekly_hours=8)
    plan = final["plan"]
    by_id = {opp["id"]: opp for opp in final["verified"]}
    for week in plan["weekly_checklist"]:
        assert week["hours"] <= 8 + 1e-6
        for allocation in week.get("allocations", []):
            deadline = by_id[allocation["opportunity_id"]]["deadline"]
            assert deadline == "rolling" or allocation["last_preparation_date"] <= deadline
    assert abs(sum(week["hours"] for week in plan["weekly_checklist"]) - plan["total_hours"]) < 0.001
    assert final["round_v"] <= 1 and final["round_c"] <= 1


def test_failed_profiler_cannot_create_confirmed_matches_or_an_application_plan():
    agents = graph.default_agents()
    def fail(state):
        raise RuntimeError("synthetic parsing failure")
    agents["profiler"] = fail
    final = graph.run(STUDENT_A, agents=agents)
    assert "profiler" in final["failures"]
    assert final["matches"] == []
    assert final["plan"]["ranked"] == []
    assert final["plan"]["improvement_tips"]


def test_no_candidates_still_finishes_with_honest_guidance():
    final = graph.run(STUDENT_A, opportunity_types=["workshop"])
    assert final["candidates"] == []
    assert final["plan"]["ranked"] == []
    assert final["plan"]["weekly_checklist"]
