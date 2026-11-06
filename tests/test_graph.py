"""Tests for graph construction and execution."""
"""Graph tests (M1). They use FAKE agents, so they keep passing when real agents replace the stubs."""
import importlib
import sys
import types

import graph
from agents import stubs
from graph import build_graph, run, stream_events
from state import AGENT_NAMES, make_msg


def make_fakes(calls, always_recheck=True, always_challenge=True):
    def scout(state):
        calls.append("scout")
        return {"candidates": [{"id": "opp_x", "deadline": "2026-12-01"}],
                "messages": [make_msg("scout", "verifier", "result", "scout ran")]}

    def profiler(state):
        calls.append("profiler")
        return {"profile": {"name": "A"},
                "messages": [make_msg("profiler", "all", "result", "profiler ran")]}

    def verifier(state):
        calls.append("verifier")
        return {"verified": state["candidates"], "rejected": [],
                "recheck": ["opp_x"] if always_recheck else [], "messages": []}

    def matcher(state):
        calls.append("matcher")
        return {"matches": [{"opportunity_id": "opp_x"}], "messages": []}

    def coach(state):
        calls.append("coach")
        return {"plan": {"ranked": []},
                "challenge": {"ids": ["opp_x"], "reason": "clash"} if always_challenge else None,
                "messages": []}

    return {"scout": scout, "profiler": profiler, "verifier": verifier,
            "matcher": matcher, "coach": coach}


# ---------- loops ----------
def test_loops_fire_once_and_stop():
    calls = []
    final = run("x", agents=make_fakes(calls))      # agents ALWAYS ask for a loop
    assert calls.count("scout") == 2                 # first run + one re-check
    assert calls.count("verifier") == 2
    assert calls.count("matcher") == 2               # first run + one re-rank
    assert calls.count("coach") == 2
    assert final["round_v"] == 1 and final["round_c"] == 1


def test_no_loops_when_nothing_to_challenge():
    calls = []
    final = run("x", agents=make_fakes(calls, always_recheck=False, always_challenge=False))
    assert calls.count("scout") == 1 and calls.count("coach") == 1
    assert final["round_v"] == 0 and final["round_c"] == 0


def test_recheck_ids_are_cleared_after_the_scout_handles_them():
    seen = []
    fakes = make_fakes([])
    def scout(state):
        seen.append(list(state.get("recheck", [])))
        return {"candidates": [{"id": "opp_x"}], "messages": []}
    fakes["scout"] = scout
    run("x", agents=fakes)
    assert seen == [[], ["opp_x"]]                   # normal run, then re-check run


# ---------- parallel branch ----------
def test_parallel_branches_both_log_messages():
    final = run("x", agents=make_fakes([]))
    texts = [m["text"] for m in final["messages"]]
    assert "scout ran" in texts and "profiler ran" in texts


# ---------- safety ----------
def test_crashing_agent_does_not_stop_the_run():
    fakes = make_fakes([], always_recheck=False, always_challenge=False)
    def boom(state):
        raise RuntimeError("kaboom")
    fakes["profiler"] = boom
    final = run("x", agents=fakes)
    assert final["plan"] == {"ranked": []}           # run still reached the Coach
    assert any(m["type"] == "error" and "kaboom" in m["text"] for m in final["messages"])


def test_agent_cannot_write_keys_it_does_not_own():
    fakes = make_fakes([], always_recheck=False, always_challenge=False)
    def sneaky(state):
        return {"profile": {"name": "B"}, "candidates": ["hacked"], "messages": []}
    fakes["profiler"] = sneaky
    final = run("x", agents=fakes)
    assert final["candidates"] != ["hacked"]
    assert any("does not own" in m["text"] for m in final["messages"])


def test_agent_returning_none_is_fine():
    fakes = make_fakes([], False, False)
    fakes["profiler"] = lambda state: None
    assert run("x", agents=fakes)["plan"] == {"ranked": []}


# ---------- events for the UI ----------
def test_on_event_is_called_for_every_agent():
    seen = []
    run("x", agents=make_fakes([], False, False), on_event=lambda node, upd: seen.append(node))
    assert set(AGENT_NAMES) <= set(seen)


def test_stream_events_ends_with_final_state():
    events = list(stream_events("x", agents=make_fakes([], False, False)))
    assert events[-1][0] == "final" and events[-1][2]["plan"] == {"ranked": []}
    assert all(e[0] == "update" for e in events[:-1])


# ---------- finding / replacing agents ----------
def test_agent_without_run_becomes_stub(monkeypatch):
    monkeypatch.setitem(sys.modules, "agents.profiler", types.ModuleType("agents.profiler"))
    fn, status = graph.load_agent("profiler")
    assert status == "stub"
    assert fn({})["profile"]["name"] == "Student A"     # fake data from agents/stubs.py


def test_broken_agent_file_becomes_stub_not_a_crash(monkeypatch):
    real_import = importlib.import_module
    def fake_import(name, *a, **k):
        if name == "agents.coach":
            raise SyntaxError("bad code")
        return real_import(name, *a, **k)
    monkeypatch.setattr(graph.importlib, "import_module", fake_import)
    fn, status = graph.load_agent("coach")
    assert status.startswith("broken") and callable(fn)


def test_real_run_function_is_used(monkeypatch):
    mod = types.ModuleType("agents.matcher")
    mod.run = lambda state: {"matches": []}
    monkeypatch.setitem(sys.modules, "agents.matcher", mod)
    fn, status = graph.load_agent("matcher")
    assert status == "real" and fn is mod.run


def test_all_stubs_run_the_full_flow_with_both_loops():
    agents = {name: getattr(stubs, name) for name in AGENT_NAMES}
    final = run("x", agents=agents)
    assert final["round_v"] == 1 and final["round_c"] == 1     # stubs trigger both loops
    assert final["plan"]["ranked"]                              # and a plan still comes out


# ---------- speed ----------
def test_default_graph_is_compiled_once():
    graph.reset_cache()
    assert build_graph() is build_graph()