"""Regressions from PROJECT_AUDIT.md, exercised with adversarial inputs."""
import copy
import json
import threading

import pytest

import graph
import llm
import replay
from agents import matcher, profiler, scout, verifier
from domain import record_errors
from runtime import Run, task_key, worker
from state import new_state
from tests.test_graph import make_fakes
from tests.test_matcher import STUDENT_A, opp
from tests.test_smoke import STUDENT_A as PROFILE_TEXT
from tests.test_verifier import _base_opp


@pytest.mark.parametrize("url", ["https://kiroween.devpost.com/rules", "https://leap.microsoft.com/en-US/",
                                 "https://official.org/path/bit.ly"])
def test_real_domains_and_irrelevant_paths_are_not_mistaken_for_shorteners(url):
    assert verifier._url_looks_unofficial(url) is False


@pytest.mark.parametrize("url", ["https://T.CO/a", "https://bit.ly/a", "javascript:alert(1)",
                                 "https://user:secret@example.org/a", "https://[invalid"])
def test_untrusted_or_malformed_links_do_not_pass(url):
    assert verifier._url_looks_unofficial(url) is True


@pytest.mark.parametrize("bad", [{"id": None}, {"deadline": 12}, {"eligibility": "broken"},
                                 {"application_fee": "true"}, {"required_skills": "Python"},
                                 {"effort_hours": -4}, {"effort_hours": float("nan")},
                                 {"eligibility": {"min_gpa": 7}}, {"source_url": "javascript:alert(1)"}])
def test_bad_record_isolated_while_valid_peer_is_retained(bad):
    malformed = {**_base_opp({"id": "bad"}), **bad}
    good = _base_opp({"id": "good"})
    out = verifier.run({"candidates": [malformed, good]})
    assert [record["id"] for record in out["verified"]] == ["good"]
    assert len(out["rejected"]) == 1
    assert record_errors(malformed)


def test_missing_id_and_nonobject_records_do_not_crash_the_batch():
    out = verifier.run({"candidates": [{"title": "Missing ID"}, "not a record", _base_opp()]})
    assert len(out["verified"]) == 1 and len(out["rejected"]) == 2


def test_scam_claim_in_description_is_rejected():
    out = verifier.run({"candidates": [_base_opp({"description": "Guaranteed selection. Pay immediately."})]})
    assert out["verified"] == []
    assert "Scam" in out["rejected"][0][1]


def test_stale_reread_keeps_uncertainty_and_never_asks_a_model_to_certify_it(monkeypatch):
    monkeypatch.setattr(llm, "ask", lambda *a, **kw: pytest.fail("Verifier must not use model opinions as evidence"))
    stale = _base_opp({"last_checked": "2000-01-01"})
    state = {"candidates": [stale], "round_v": 0}
    first = verifier.run(state)
    assert first["recheck"] == [stale["id"]]
    second = verifier.run({**state, "round_v": 1})
    assert second["recheck"] == []
    assert second["verified"][0]["verification_status"] == "needs_review"
    assert second["verified"][0]["source_checked_live"] is False


def test_profile_sections_are_not_mixed_and_unknowns_are_preserved():
    profile = profiler.run({"student_input": PROFILE_TEXT})["profile"]
    assert profile["name"] == "Ahmed Ali" and profile["year"] == 3 and profile["gpa"] == 3.3
    assert profile["skills"] == ["Python", "Machine Learning", "HTML"]
    assert profile["projects"] == ["Student grade tracker"]
    assert profile["interests"] == ["AI internships", "scholarships"]
    missing = profiler.run({"student_input": "Year: 1\nSkills: HTML\nGPA: 9.0"})["profile"]
    assert missing["gpa"] is None and "gpa" in missing["missing_fields"]


def test_model_enrichment_cannot_invent_qualifications(monkeypatch):
    monkeypatch.setattr(llm, "ask", lambda *a, **kw: ({"skills": ["Python", "Java"], "gpa": 4,
                        "year": 4, "projects": ["Won a global competition"]}, "fake"))
    p = profiler.run({"student_input": "Year: 1\nField: Business", "use_llm": True})["profile"]
    assert p["year"] == 1 and p["gpa"] is None and not p["skills"] and not p["projects"]


@pytest.mark.parametrize("have,required", [("JavaScript", "Java"), ("C++", "C"), ("React Native", "React")])
def test_distinct_skills_do_not_pass_by_substring(have, required):
    assert matcher.has_skill([have], required) is False


def test_unknown_eligibility_is_conditional_not_confirmed():
    status, reasons = matcher.assess_eligibility({}, opp("a", min_year=4, min_gpa=3.9,
                                                    fields=["Medicine"], nationalities=["American"]))
    assert status == "conditional"
    assert len(reasons) == 4


def test_field_and_nationality_aliases_do_not_create_false_rejections():
    student = {**STUDENT_A, "field": "CS", "nationality": "Pakistan"}
    assert matcher.check_eligibility(student, opp("a", fields=["Computer Science"], nationalities=["Pakistani"]))[0]


def test_unrecorded_skills_do_not_receive_an_unsupported_perfect_skill_score():
    opportunity = {**opp("a"), "required_skills": [], "eligibility_complete": False}
    score, reasons, _ = matcher.score_match(STUDENT_A, opportunity)
    assert any("neutral" in reason for reason in reasons)
    assert score < 80


def test_scout_deduplicates_before_limit_and_honors_type_filters(monkeypatch):
    a, duplicate, b = opp("a"), opp("copy"), opp("b")
    b["source_url"] = "https://other.example.org/b"
    b["type"] = "scholarship"
    monkeypatch.setattr(scout, "load_index", lambda: scout.build_index([a, duplicate, b]))
    out = scout.run({"student_input": "Interests: AI internships", "opportunity_types": ["internship"]})
    assert [o["id"] for o in out["candidates"]] == ["a"]


@pytest.mark.parametrize("bad", [["bad"], "bad", {"candidates": "bad"}, {"messages": ["bad"]}])
def test_agent_guard_converts_bad_outputs_into_visible_failures(bad):
    out = graph.guarded("scout", lambda state: bad)(new_state("test"))
    assert out["candidates"] == [] and out["failures"] == ["scout"]


def test_agents_cannot_mutate_shared_nested_input():
    state = new_state("test")
    state["profile"] = {"skills": ["Python"]}
    def mutates(value):
        value["profile"]["skills"].append("Invented skill")
        return {"candidates": []}
    graph.guarded("scout", mutates)(state)
    assert state["profile"]["skills"] == ["Python"]


def test_lifecycle_events_prove_parallel_start_and_join():
    fakes = make_fakes([], False, False)
    profiler_started = threading.Event()
    def find(state):
        assert profiler_started.wait(2), "Profiler should run concurrently with Scout"
        return {"candidates": []}
    def profile(state):
        profiler_started.set()
        return {"profile": {"name": "A"}}
    fakes.update(scout=find, profiler=profile)
    events = [e[2] for e in graph.stream_events("test", agents=fakes) if e[0] == "activity"]
    positions = {(e["agent"], e["phase"]): i for i, e in enumerate(events)}
    assert positions[("profiler", "started")] < positions[("scout", "completed")]
    assert positions[("verifier", "started")] > max(positions[("scout", "completed")], positions[("profiler", "completed")])


def test_recording_is_atomic_scoped_validated_and_replays_without_agents(monkeypatch, tmp_path):
    monkeypatch.setattr(replay, "CACHE_DIR", tmp_path)
    events = list(graph.stream_events(PROFILE_TEXT))
    replay.save_run("last_run", PROFILE_TEXT, events, events[-1][2], namespace="a" * 32)
    assert replay.load_run("last_run", namespace="b" * 32) is None
    monkeypatch.setattr(graph, "stream_events", lambda *a, **kw: pytest.fail("Replay must not run agents"))
    assert list(replay.replay_events("last_run", namespace="a" * 32))[-1][2] == json.loads(json.dumps(events[-1][2]))
    assert not list(tmp_path.rglob("*.tmp"))


@pytest.mark.parametrize("name", ["../escape", "a/b", "C:\\escape", "", ".env"])
def test_recording_paths_cannot_escape(name):
    with pytest.raises(ValueError):
        replay._path(name)


def test_broken_recordings_raise_a_friendly_error(monkeypatch, tmp_path):
    monkeypatch.setattr(replay, "CACHE_DIR", tmp_path)
    (tmp_path / "broken.json").write_text('{"events":[]}', encoding="utf-8")
    assert replay.load_run("broken") is None
    with pytest.raises(ValueError, match="damaged"):
        list(replay.replay_events("broken"))


def test_save_failure_does_not_turn_successful_analysis_into_a_failure(monkeypatch):
    def fail(*a, **kw):
        raise OSError("synthetic disk failure")
    monkeypatch.setattr(replay, "save_run", fail)
    run = Run()
    worker(run, PROFILE_TEXT, namespace="a" * 32)
    assert run.final and run.error is None and run.warning


def test_different_plan_tasks_do_not_inherit_completion_keys():
    assert task_key("first", 1, "Review rules") != task_key("second", 1, "Review rules")
    assert task_key("first", 1, "Review rules") != task_key("first", 1, "New task")
