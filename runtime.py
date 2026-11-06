"""Background execution and UI event state, independent of Streamlit."""
import hashlib
import queue
import threading
from dataclasses import dataclass, field

import graph
import replay


@dataclass
class Run:
    events: queue.Queue = field(default_factory=queue.Queue)
    done: threading.Event = field(default_factory=threading.Event)
    journal: list = field(default_factory=list)
    final: dict | None = None
    error: str | None = None
    warning: str | None = None


def worker(run, text, *, namespace, options=None, recording=None, recorded_events=None):
    try:
        source = (iter(recorded_events) if recorded_events is not None else
                  replay.replay_events(recording) if recording else graph.stream_events(text, **(options or {})))
        for event in source:
            run.journal.append(event)
            run.events.put(event)
            if event[0] == "final":
                run.final = event[2]
        if run.final is None:
            raise ValueError("The workflow ended without a result. Start a new analysis.")
        if not recording and recorded_events is None:
            try:
                replay.save_run("last_run", text, run.journal, run.final, namespace=namespace)
            except (OSError, ValueError) as exc:
                run.warning = "Your analysis is complete, but the recording could not be saved. You can still download your results."
    except Exception as exc:
        run.error = f"The analysis could not finish: {str(exc)[:200]}"
    finally:
        run.done.set()


def launch(text, *, namespace, options=None, recording=None, recorded_events=None):
    run = Run()
    threading.Thread(target=worker, args=(run, text), kwargs={"namespace": namespace, "options": options,
                     "recording": recording, "recorded_events": recorded_events}, daemon=True).start()
    return run


def task_key(run_id, week, task):
    digest = hashlib.sha256(f"{run_id}|{week}|{task}".encode()).hexdigest()[:20]
    return "task_" + digest


def empty_view():
    return {"agents": {}, "messages": [], "activity": [], "final": None}


def apply_event(view, event):
    kind, name, payload = event
    if kind == "activity":
        view["activity"].append(payload)
        view["agents"][name] = payload
    elif kind == "update":
        view["messages"].extend(payload.get("messages", []))
    elif kind == "final":
        view["final"] = payload
        # Preserve the initial system message and exact final log for exports and replay.
        view["messages"] = payload.get("messages", view["messages"])


def drain(run, view, *, limit=None):
    count = 0
    while limit is None or count < limit:
        try:
            event = run.events.get_nowait()
        except queue.Empty:
            break
        apply_event(view, event)
        count += 1
    return run.done.is_set() and run.events.empty()


def plan_markdown(final):
    profile, plan = final.get("profile", {}), final.get("plan", {})
    lines = ["# Your Futurist plan", "", f"Prepared for {profile.get('name', 'Student')} on {final.get('run_date', '')}.",
             "", "Source details are from a local catalog. Confirm current eligibility and deadlines before applying.", ""]
    for item in plan.get("ranked", []):
        lines += [f"## {item['rank']}. {item.get('title', item['opportunity_id'])}", "", item.get("why", ""), "",
                  f"Source: {item.get('source_url', '')}", ""]
    for week in plan.get("weekly_checklist", []):
        lines += [f"## Week {week['week']} — {week.get('hours', 0):g} hours", ""]
        lines += [f"- [ ] {task}" for task in week.get("tasks", [])]
        lines.append("")
    lines += ["## Improvement tips", ""] + [f"- {tip}" for tip in plan.get("improvement_tips", [])]
    return "\n".join(lines)
