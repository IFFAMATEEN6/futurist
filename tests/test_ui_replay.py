"""Streamlit user-flow checks: local execution, validation, replay and task isolation."""
import time
import threading
import urllib.request

import pytest
from streamlit.testing.v1 import AppTest

import config
import graph
import llm
import replay
from tests.test_smoke import STUDENT_A


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setattr(replay, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(config, "REPLAY_MODE", False)
    def no_network(*args, **kwargs):
        raise AssertionError("This local workflow must not access a provider or probe the network")
    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    monkeypatch.setattr(llm, "ask", no_network)
    at = AppTest.from_file(str(config.BASE_DIR / "app.py"), default_timeout=20).run()
    assert not at.exception
    return at


def button(at, label):
    return next(value for value in at.button if value.label == label)


def finish(at):
    for _ in range(50):
        assert not at.exception
        if not at.session_state["running"]:
            return at
        time.sleep(0.01)
        at.run()
    raise AssertionError("UI did not finish its workflow")


def analyze(at, text=STUDENT_A):
    at.toggle[0].set_value(False).run()
    at.text_area[0].set_value(text).run()
    button(at, "Find my opportunities").click().run()
    return finish(at)


def test_empty_input_stays_in_workspace_and_explains_what_is_missing(app):
    button(app, "Find my opportunities").click().run()
    assert not app.exception
    assert "profile details" in app.session_state["form_error"]
    assert app.session_state["view"]["final"] is None


def test_full_local_user_flow_shows_five_agents_links_plan_and_exports(app):
    analyze(app)
    final = app.session_state["view"]["final"]
    assert final["plan"]["ranked"]
    assert final["profile"]["name"] == "Ahmed Ali"
    assert set(app.session_state["view"]["agents"]) == {"scout", "profiler", "verifier", "matcher", "coach"}
    assert all(value["phase"] == "completed" for value in app.session_state["view"]["agents"].values())
    assert [tab.label for tab in app.tabs] == ["Your shortlist", "Weekly plan", "Profile & skills"]
    assert len(app.get("download_button")) == 2
    assert app.get("link_button")
    html = "".join(element.proto.body for element in app.get("html"))
    assert "Meets recorded rules" not in html  # The shipped catalog explicitly has incomplete eligibility.
    assert "Confirm eligibility" in html and "stub" not in html


def test_guided_profile_rejects_bad_gpa_then_recovers(app):
    app.session_state["entry_mode"] = "Guided fields"
    app.run()
    next(v for v in app.text_input if v.label == "Name").set_value("Ayesha")
    next(v for v in app.text_input if v.label == "Field of study").set_value("Computer Science")
    next(v for v in app.text_input if v.label == "Skills").set_value("Python, HTML")
    next(v for v in app.text_input if v.label.startswith("GPA")).set_value("9.3")
    button(app, "Find my opportunities").click().run()
    assert "GPA" in app.session_state["form_error"] and not app.session_state["running"]
    next(v for v in app.text_input if v.label.startswith("GPA")).set_value("3.3")
    app.toggle[0].set_value(False).run()
    button(app, "Find my opportunities").click().run()
    finish(app)
    assert app.session_state["view"]["final"]["profile"]["gpa"] == 3.3


def test_replay_does_not_run_agents_again(app, monkeypatch):
    analyze(app)
    expected = app.session_state["view"]["final"]
    def no_graph(*args, **kwargs):
        raise AssertionError("Replay must use recorded events")
    monkeypatch.setattr(graph, "stream_events", no_graph)
    button(app, "Replay my last analysis").click().run()
    finish(app)
    assert app.session_state["is_replay"] is True
    assert app.session_state["view"]["final"] == expected


def test_checked_tasks_persist_in_one_plan_and_reset_for_a_new_plan(app):
    analyze(app)
    task = next(c for c in app.checkbox if c.key and c.key.startswith("task_"))
    first_key = task.key
    task.check().run()
    assert next(c for c in app.checkbox if c.key == first_key).value is True
    button(app, "Find my opportunities").click().run()
    finish(app)
    tasks = [c for c in app.checkbox if c.key and c.key.startswith("task_")]
    assert first_key not in [c.key for c in tasks]
    assert all(c.value is False for c in tasks)


def test_no_opportunity_type_selection_cannot_start_a_run(app):
    app.text_area[0].set_value(STUDENT_A)
    app.multiselect[0].set_value([])
    button(app, "Find my opportunities").click().run()
    assert "at least one" in app.session_state["form_error"]
    assert app.session_state["view"]["final"] is None


def test_profile_html_is_escaped_in_results(app):
    analyze(app, STUDENT_A.replace("Ahmed Ali", '<img src=x onerror="alert(1)">'))
    html = "".join(element.proto.body for element in app.get("html"))
    assert '<img src=x onerror="alert(1)">' not in html
    assert "&lt;img" in html


def test_new_session_does_not_show_another_sessions_private_replay(app):
    analyze(app)
    other = AppTest.from_file(str(config.BASE_DIR / "app.py")).run()
    assert other.session_state["session_id"] != app.session_state["session_id"]
    assert "Replay my last analysis" not in [b.label for b in other.button]


def test_active_agent_is_visible_and_duplicate_start_is_disabled(app, monkeypatch):
    original = graph.stream_events
    release = threading.Event()
    def held(*args, **kwargs):
        yield "activity", "scout", {"agent": "scout", "phase": "started", "pass": 1, "ts": "2026-11-07T12:00:00"}
        if not release.wait(5):
            raise RuntimeError("test did not release the held agent")
        yield from original(*args, **kwargs)
    monkeypatch.setattr(graph, "stream_events", held)
    app.toggle[0].set_value(False).run()
    app.text_area[0].set_value(STUDENT_A)
    button(app, "Find my opportunities").click().run()
    try:
        assert app.session_state["running"] is True
        assert button(app, "Find my opportunities").disabled
        app.run()
        assert app.session_state["view"]["agents"]["scout"]["phase"] == "started"
        html = "".join(element.proto.body for element in app.get("html"))
        assert "Searching the local catalog" in html and "Working" in html
    finally:
        release.set()
    finish(app)


def test_changing_activity_preferences_preserves_an_unsubmitted_profile_draft(app):
    app.text_area[0].set_value("My profile draft with Python and HTML").run()
    app.toggle[0].set_value(False).run()
    assert app.text_area[0].value == "My profile draft with Python and HTML"
