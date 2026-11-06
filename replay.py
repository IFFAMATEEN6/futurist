"""Save and replay a demo run. Owner: M3."""
import json
from pathlib import Path

import config

CACHE_DIR = Path(config.CACHE_DIR)


def _path(name):
    return CACHE_DIR / f"{name}.json"


def save_run(name, student_input, events, final):
    """events: list of (kind, node_name, payload) tuples. Returns the file path."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data = {"student_input": student_input,
            "events": [[k, n, p] for k, n, p in events],
            "final": final}
    p = _path(name)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str),
                 encoding="utf-8")
    return p


def list_runs():
    if not CACHE_DIR.exists():
        return []
    return sorted(p.stem for p in CACHE_DIR.glob("*.json"))


def load_run(name):
    """Return the saved dict, or None if missing or broken."""
    try:
        return json.loads(_path(name).read_text(encoding="utf-8"))
    except Exception:
        return None


def replay_events(name):
    """Yield the saved events in order, same shape as graph.stream_events. No API calls."""
    data = load_run(name)
    if not data:
        return
    for kind, node, payload in data["events"]:
        yield kind, node, payload