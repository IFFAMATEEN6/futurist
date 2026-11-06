"""LangGraph workflow. Owner: M1.
"""
import importlib
import copy
import time
from collections.abc import Mapping
from functools import lru_cache

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

import config
from state import AGENT_NAMES, OWNED_KEYS, OpportunityState, error_msg, make_msg, new_state


# ---------- finding the agents ----------
def _unavailable(name, reason):
    def failed(state):
        raise RuntimeError(f"{name} is unavailable: {reason}")
    return failed


def load_agent(name: str):
    """Return (function, status); unavailable modules fail visibly, never use stubs."""
    try:
        module = importlib.import_module(f"agents.{name}")
    except Exception as exc:                      # e.g. a syntax error in a teammate's file
        return _unavailable(name, str(exc)), f"broken ({exc.__class__.__name__})"
    fn = getattr(module, "run", None)
    if callable(fn):
        return fn, "real"
    return _unavailable(name, "missing run() entry point"), "unavailable"


def agent_status() -> dict:
    """Report each production module's real/unavailable/broken status."""
    return {name: load_agent(name)[1] for name in AGENT_NAMES}


def default_agents() -> dict:
    return {name: load_agent(name)[0] for name in AGENT_NAMES}


# ---------- safety wrapper ----------
def guarded(name: str, fn):
    """Wrap an agent: catch crashes, drop keys it does not own."""
    allowed = OWNED_KEYS[name] | {"messages"}

    def node(state):
        started = time.perf_counter()
        try:
            writer = get_stream_writer()
        except RuntimeError:
            writer = lambda event: None
        round_number = 1 + state.get("round_v" if name in ("scout", "verifier") else "round_c", 0)
        if (name == "scout" and state.get("recheck")) or (name == "matcher" and state.get("challenge")):
            round_number += 1
        writer({"agent": name, "phase": "started", "pass": round_number,
                "ts": make_msg(name, "all", "info", "")["ts"]})
        try:
            out = fn(copy.deepcopy(state)) or {}
            if not isinstance(out, Mapping):
                raise TypeError("agent output must be a mapping")
            clean = {k: v for k, v in out.items() if k in allowed}
            for key, value in clean.items():
                expected = dict if key in ("profile", "plan", "recheck_evidence") else list
                if key == "challenge":
                    if value is not None and not isinstance(value, dict):
                        raise TypeError("challenge must be an object or null")
                elif not isinstance(value, expected):
                    raise TypeError(f"{key} must be {expected.__name__}")
            for msg in clean.get("messages", []):
                if not isinstance(msg, dict) or not all(isinstance(msg.get(k), str) for k in ("sender", "recipient", "type", "text")):
                    raise TypeError("messages must follow the shared message contract")
            profile = clean.get("profile", {})
            for key in ("skills", "interests", "projects", "strength_notes"):
                if key in profile and (not isinstance(profile[key], list) or any(not isinstance(v, str) for v in profile[key])):
                    raise TypeError(f"profile.{key} must be a list of strings")
            for match in clean.get("matches", []):
                if not isinstance(match, dict) or not isinstance(match.get("opportunity_id"), str):
                    raise TypeError("matches must contain opportunity identities")
            plan = clean.get("plan", {})
            for key in ("ranked", "weekly_checklist", "improvement_tips", "deferred"):
                if key in plan and not isinstance(plan[key], list):
                    raise TypeError(f"plan.{key} must be a list")
            for item in plan.get("ranked", []):
                if not isinstance(item, dict) or not isinstance(item.get("opportunity_id"), str) or not isinstance(item.get("rank"), int):
                    raise TypeError("ranked priorities must contain an identity and numeric rank")
            for week in plan.get("weekly_checklist", []):
                if (not isinstance(week, dict) or not isinstance(week.get("week"), int)
                        or not isinstance(week.get("tasks"), list) or any(not isinstance(task, str) for task in week["tasks"])):
                    raise TypeError("weekly checklist must contain numbered weeks and text tasks")
            dropped = sorted(set(out) - allowed)
            if dropped:
                clean["messages"] = list(clean.get("messages", [])) + [
                    error_msg("system", f"{name} tried to write keys it does not own: {dropped}")]
        except Exception as exc:                  # an agent must never take the whole run down
            clean = {key: (None if key == "challenge" else {} if key in ("profile", "plan", "recheck_evidence") else [])
                     for key in OWNED_KEYS[name]}
            clean["messages"] = [error_msg(name, f"{name.capitalize()} failed: {str(exc)[:200]}")]
        failed = any(m.get("type") == "error" for m in clean.get("messages", []))
        if failed:
            clean["failures"] = [name]
        writer({"agent": name, "phase": "failed" if failed else "completed", "pass": round_number,
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "ts": make_msg(name, "all", "info", "")["ts"]})
        return clean
    return node


# ---------- routing (the two loops) ----------
def after_verifier(state) -> str:
    """Loop 1: doubtful items go back to the Scout, once."""
    if state.get("recheck") and state.get("round_v", 0) < config.MAX_VERIFIER_ROUNDS:
        return "rescout"
    return "matcher"


def after_coach(state) -> str:
    """Loop 2: a Coach challenge goes to the Matcher, once."""
    if state.get("challenge") and state.get("round_c", 0) < config.MAX_COACH_ROUNDS:
        return "rematch"
    return END


# ---------- building the graph ----------
def _compile(agents: dict):
    nodes = {name: guarded(name, agents[name]) for name in AGENT_NAMES}

    def rescout(state):
        out = nodes["scout"](state)               # Scout sees state["recheck"] and re-checks
        out["round_v"] = state.get("round_v", 0) + 1
        out["recheck"] = []                       # ids handled
        return out

    def rematch(state):
        out = nodes["matcher"](state)             # Matcher sees state["challenge"] and re-ranks
        out["round_c"] = state.get("round_c", 0) + 1
        return out

    g = StateGraph(OpportunityState)
    for name in AGENT_NAMES:
        g.add_node(name, nodes[name])
    g.add_node("rescout", rescout)
    g.add_node("rematch", rematch)

    g.add_edge(START, "scout")
    g.add_edge(START, "profiler")
    g.add_edge(["scout", "profiler"], "verifier")            # waits for BOTH branches
    g.add_conditional_edges("verifier", after_verifier, {"rescout": "rescout", "matcher": "matcher"})
    g.add_edge("rescout", "verifier")
    g.add_edge("matcher", "coach")
    g.add_conditional_edges("coach", after_coach, {"rematch": "rematch", END: END})
    g.add_edge("rematch", "coach")
    return g.compile()


@lru_cache(maxsize=1)
def _default_app():
    return _compile(default_agents())


def reset_cache():
    """Call after changing agent files while the process keeps running."""
    _default_app.cache_clear()


def build_graph(agents: dict = None):
    """The compiled graph. With no argument it is built once and reused (cheap for the UI).
    Pass `agents` (name -> function) to test with fakes."""
    return _default_app() if agents is None else _compile(agents)


# ---------- running it ----------
def stream_events(student_input: str, interests_override=None, agents: dict = None, *,
                  weekly_hours=10, opportunity_types=None, use_llm=False):
    """Yield activity and update events, then ("final", None, final_state).
    The UI (M3) can read this from a background thread and push events into a queue."""
    app = build_graph(agents)
    final = None
    for mode, chunk in app.stream(new_state(student_input, interests_override, weekly_hours=weekly_hours,
                                            opportunity_types=opportunity_types, use_llm=use_llm),
                                  stream_mode=["custom", "updates", "values"]):
        if mode == "updates":
            for node_name, update in chunk.items():
                yield "update", node_name, update
        elif mode == "custom":
            yield "activity", chunk.get("agent"), chunk
        else:
            final = chunk
    yield "final", None, final


def run(student_input: str, interests_override=None, on_event=None, agents: dict = None, **options) -> dict:
    """Run the whole workflow and return the final state.
    on_event(node_name, update) is called after every step (to light up the agent cards)."""
    final = None
    for kind, name, payload in stream_events(student_input, interests_override, agents, **options):
        if kind == "update" and on_event:
            on_event(name, payload)
        elif kind == "final":
            final = payload
    return final


if __name__ == "__main__":
    demo = ("Third-year Computer Science, GPA 3.3. Skills: Python, basic machine learning, "
            "HTML. Interests: AI internships and scholarships")
    print("Agent status:", agent_status())
    result = run(demo)
    for m in result["messages"]:
        print(f"[{m['type']:<9}] {m['sender']:>8} -> {m['recipient']:<8} {m['text']}")
