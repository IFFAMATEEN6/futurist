"""Validated recordings with atomic, session-scoped persistence and offline playback."""
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import config

CACHE_DIR = Path(config.CACHE_DIR)
MAX_RECORDING_BYTES = 10 * 1024 * 1024


def _path(name, namespace=None):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", name):
        raise ValueError("Recording names may contain only letters, numbers, underscores and hyphens.")
    folder = CACHE_DIR
    if namespace is not None:
        if not isinstance(namespace, str) or not re.fullmatch(r"[a-f0-9]{32}", namespace):
            raise ValueError("Invalid session recording namespace.")
        folder = folder / "sessions" / namespace
    return folder / f"{name}.json"


def validate_run(data):
    if not isinstance(data, dict) or not isinstance(data.get("final"), dict):
        raise ValueError("Recording has no final workflow result.")
    events = data.get("events")
    if not isinstance(events, list) or not events or len(events) > 2000:
        raise ValueError("Recording event list is missing or invalid.")
    for event in events:
        if not isinstance(event, (list, tuple)) or len(event) != 3:
            raise ValueError("Invalid recorded event shape.")
        kind, name, payload = event
        if kind not in ("activity", "update", "final") or not isinstance(payload, dict):
            raise ValueError("Invalid recorded event payload.")
        if kind != "final" and name not in ("scout", "profiler", "verifier", "matcher", "coach", "rescout", "rematch"):
            raise ValueError("Recording references an unknown agent.")
    if events[-1][0] != "final" or events[-1][2] != data["final"]:
        raise ValueError("Recording is incomplete or final result does not match its events.")
    final = data["final"]
    for key in ("candidates", "verified", "rejected", "matches", "messages"):
        if not isinstance(final.get(key), list):
            raise ValueError(f"Recording result has invalid {key}.")
    if not isinstance(final.get("plan"), dict) or not isinstance(final.get("profile"), dict):
        raise ValueError("Recording profile or plan is malformed.")
    for message in final["messages"]:
        if not isinstance(message, dict) or not all(isinstance(message.get(k), str) for k in ("sender", "recipient", "type", "text")):
            raise ValueError("Recording contains a malformed message.")
    ids = {record.get("id") for record in final["verified"] if isinstance(record, dict) and isinstance(record.get("id"), str)}
    for match in final["matches"]:
        if not isinstance(match, dict) or match.get("opportunity_id") not in ids or match.get("eligibility_status") not in ("eligible", "conditional", "ineligible"):
            raise ValueError("Recording contains an invalid match.")
    plan = final["plan"]
    if not isinstance(plan.get("ranked"), list) or not isinstance(plan.get("weekly_checklist"), list):
        raise ValueError("Recording contains an invalid plan.")
    for item in plan["ranked"]:
        if not isinstance(item, dict) or item.get("opportunity_id") not in ids or not isinstance(item.get("rank"), int):
            raise ValueError("Recording contains an invalid ranked opportunity.")
    for week in plan["weekly_checklist"]:
        if (not isinstance(week, dict) or not isinstance(week.get("week"), int)
                or not isinstance(week.get("tasks"), list) or any(not isinstance(task, str) for task in week["tasks"])):
            raise ValueError("Recording contains an invalid checklist.")
    return data


def save_run(name, student_input, events, final, *, namespace=None):
    data = {"version": 2, "created_at": datetime.now(timezone.utc).isoformat(),
            "recorded_date": final.get("run_date"), "student_input": student_input,
            "events": [[k, n, p] for k, n, p in events], "final": final}
    validate_run(data)
    path = _path(name, namespace)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            json.dump(data, file, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return path


def list_runs(*, namespace=None):
    folder = _path("last_run", namespace).parent
    return sorted(path.stem for path in folder.glob("*.json")) if folder.exists() else []


def load_run(name, *, namespace=None):
    path = _path(name, namespace)
    try:
        if path.stat().st_size > MAX_RECORDING_BYTES:
            return None
        return validate_run(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return None


def replay_events(name, *, namespace=None):
    data = load_run(name, namespace=namespace)
    if data is None:
        raise ValueError("This recording is missing, incomplete or damaged. Start a new analysis to create a recording.")
    yield from (tuple(event) for event in data["events"])
