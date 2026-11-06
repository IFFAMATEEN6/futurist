"""LangGraph workflow. Owner: M1.

    START -> scout  \
                      >-- (both finish) --> verifier --> matcher --> coach --> END
    START -> profiler /          ^    |                     ^         |
                                 |    +-- doubtful? --+      |         +-- clash? --+
                                 +------ rescout <---+      +-- rematch <-----------+
                                 (max 1 round)                (max 1 round)

How it stays modular and safe:
  * Agents are discovered by name from agents/<name>.py (list lives in state.OWNED_KEYS).
    A missing, empty or broken agent file is replaced by a fake agent from agents/stubs.py,
    so one member's unfinished work never blocks the others.
  * Every agent is wrapped by guarded(): a crash only adds an error message, and any key the
    agent does not own is dropped and reported.
  * The two loops are counted here, so they can never run more than once.
  * The compiled graph is cached, and Scout/Profiler run in parallel (the Profiler's network
    wait does not slow Scout down).
"""
import importlib
from functools import lru_cache

from langgraph.graph import END, START, StateGraph

import config
from agents import stubs
from state import AGENT_NAMES, OWNED_KEYS, OpportunityState, error_msg, make_msg, new_state


# ---------- finding the agents ----------
def _stub(name: str):
    """The fake agent (agents/stubs.py) used while the real one has no run() yet."""
    return getattr(stubs, name)


def load_agent(name: str):
    """Return (function, status). status: 'real', 'stub' or 'broken (reason)'."""
    try:
        module = importlib.import_module(f"agents.{name}")
    except Exception as exc:                      # e.g. a syntax error in a teammate's file
        return _stub(name), f"broken ({exc.__class__.__name__}: {exc})"
    fn = getattr(module, "run", None)
    if callable(fn):
        return fn, "real"
    return _stub(name), "stub"


def agent_status() -> dict:
    """{'scout': 'real', 'profiler': 'stub', ...}"""
    return {name: load_agent(name)[1] for name in AGENT_NAMES}


def default_agents() -> dict:
    return {name: load_agent(name)[0] for name in AGENT_NAMES}


# ---------- safety wrapper ----------
def guarded(name: str, fn):
    """Wrap an agent: catch crashes, drop keys it does not own."""
    allowed = OWNED_KEYS[name] | {"messages"}

    def node(state):
        try:
            out = fn(state) or {}
        except Exception as exc:                  # an agent must never take the whole run down
            return {"messages": [error_msg(name, f"{name} failed: {exc}")]}
        clean = {k: v for k, v in out.items() if k in allowed}
        dropped = sorted(set(out) - allowed)
        if dropped:
            clean["messages"] = list(clean.get("messages", [])) + [
                error_msg("system", f"{name} tried to write keys it does not own: {dropped}")]
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
def stream_events(student_input: str, interests_override=None, agents: dict = None):
    """Yield ("update", node_name, update) after every step, then ("final", None, final_state).
    The UI (M3) can read this from a background thread and push events into a queue."""
    app = build_graph(agents)
    final = None
    for mode, chunk in app.stream(new_state(student_input, interests_override),
                                  stream_mode=["updates", "values"]):
        if mode == "updates":
            for node_name, update in chunk.items():
                yield "update", node_name, update
        else:
            final = chunk
    yield "final", None, final


def run(student_input: str, interests_override=None, on_event=None, agents: dict = None) -> dict:
    """Run the whole workflow and return the final state.
    on_event(node_name, update) is called after every step (to light up the agent cards)."""
    final = None
    for kind, name, payload in stream_events(student_input, interests_override, agents):
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