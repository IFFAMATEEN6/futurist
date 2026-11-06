"""Streamlit UI. Owner: M3."""
import queue
import socket
import threading
import time

import streamlit as st

import graph
import replay
from state import AGENT_NAMES

PREREQS = {"scout": [], "profiler": [], "verifier": ["scout", "profiler"],
           "matcher": ["verifier"], "coach": ["matcher"]}
NODE_TO_AGENT = {"rescout": "scout", "rematch": "matcher"}
TYPE_ICON = {"info": "ℹ️", "result": "✅", "challenge": "⚔️",
             "response": "↩️", "reject": "🚫", "error": "❗"}


class Run:
    """Holds one background run. The thread only touches this object, never st.session_state."""
    def __init__(self):
        self.events = queue.Queue()
        self.done = False
        self.final = None
        self.error = None


def _worker(run, text, replay_name=None):
    events = []
    try:
        if replay_name:
            source = replay.replay_events(replay_name)
        else:
            source = graph.stream_events(text)
        for kind, name, payload in source:
            events.append((kind, name, payload))
            run.events.put((kind, name, payload))
            if replay_name:
                time.sleep(0.6)   # slow down so the cards visibly light up
        if not replay_name:
            final = next((p for k, n, p in events if k == "final"), None)
            if final:
                replay.save_run("last_run", text, events, final)
    except Exception as exc:
        run.error = str(exc)
    finally:
        run.done = True


def is_online():
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=1.5).close()
        return True
    except OSError:
        return False


st.set_page_config(page_title="Opportunity Intelligence Network", layout="wide")
ss = st.session_state
ss.setdefault("run", None)
ss.setdefault("running", False)
ss.setdefault("done_agents", set())
ss.setdefault("messages", [])
ss.setdefault("final", None)
ss.setdefault("online", is_online())

# ---------- drain events from the background thread ----------
run = ss.run
if run is not None and ss.running:
    finished = run.done          # read BEFORE draining, so no event is lost
    while True:
        try:
            kind, name, payload = run.events.get_nowait()
        except queue.Empty:
            break
        if kind == "update":
            ss.done_agents.add(NODE_TO_AGENT.get(name, name))
            ss.messages.extend((payload or {}).get("messages", []))
        elif kind == "final":
            run.final = payload
    if finished:
        ss.running = False
        ss.final = run.final
        if run.error:
            ss.messages.append({"sender": "system", "recipient": "all", "type": "error",
                                "text": f"Run failed: {run.error}"})

# ---------- header and input ----------
st.title("Opportunity Intelligence Network")
if not ss.online:
    st.warning("You are offline. The run will still finish using the local dataset.")

text = st.text_area("Paste your student profile", height=160, key="student_text",
                    placeholder="I'm Ayesha, a third-year Computer Science student, GPA 3.3 ...")
c1, c2 = st.columns(2)
start = c1.button("Start", type="primary", disabled=ss.running)
saved = replay.list_runs()
do_replay = c2.button("▶ Replay last saved run", disabled=ss.running or not saved)
if do_replay and not ss.running and "last_run" in saved:
    ss.online = True
    ss.done_agents = set()
    ss.messages = []
    ss.final = None
    ss.running = True
    ss.run = Run()
    threading.Thread(target=_worker, args=(ss.run, "", "last_run"), daemon=True).start()
if start and not ss.running:
    if not text.strip():
        st.warning("Please paste a profile first.")
    else:
        ss.online = is_online()
        ss.done_agents = set()
        ss.messages = []
        ss.final = None
        ss.running = True
        ss.run = Run()
        threading.Thread(target=_worker, args=(ss.run, text), daemon=True).start()

# ---------- agent cards ----------
st.subheader("Agents")
cols = st.columns(len(AGENT_NAMES))
for col, name in zip(cols, AGENT_NAMES):
    if name in ss.done_agents:
        status = "✅ Done"
    elif ss.running and all(p in ss.done_agents for p in PREREQS[name]):
        status = "⏳ Working..."
    else:
        status = "⏸ Waiting"
    last = next((m["text"] for m in reversed(ss.messages) if m.get("sender") == name), "")
    with col:
        st.markdown(f"**{name.capitalize()}**")
        st.write(status)
        if last:
            st.caption(last)

# ---------- message feed ----------
with st.expander("Message log", expanded=True):
    if not ss.messages:
        st.caption("No messages yet.")
    for m in ss.messages:
        icon = TYPE_ICON.get(m.get("type"), "•")
        st.markdown(f"{icon} **{m.get('sender')}** → {m.get('recipient')}: {m.get('text')}")

# ---------- results ----------
final = ss.final
if final and not ss.running:
    st.divider()
    profile = final.get("profile") or {}
    plan = final.get("plan") or {}
    titles = {o["id"]: o.get("title", o["id"])
              for o in (final.get("candidates") or []) + (final.get("verified") or [])
              if isinstance(o, dict) and "id" in o}

    st.subheader("Your profile")
    st.metric("Strength", f"{profile.get('strength_score', '?')}/100")
    for note in profile.get("strength_notes", []):
        st.write(f"- {note}")

    st.subheader("Ranked plan")
    if not plan.get("ranked"):
        st.info("No eligible opportunities found. See the tips below.")
    for r in plan.get("ranked", []):
        oid = r.get("opportunity_id")
        st.markdown(f"**#{r.get('rank')} {titles.get(oid, oid)}**  "
                    f"deadline {r.get('deadline')}, about {r.get('effort_hours', '?')} h")
        st.write(r.get("why", ""))

    st.subheader("Weekly checklist")
    for w in plan.get("weekly_checklist", []):
        st.markdown(f"**Week {w.get('week')}**")
        for i, task in enumerate(w.get("tasks", [])):
            st.checkbox(task, key=f"chk_{w.get('week')}_{i}")

    st.subheader("Improvement tips")
    for tip in plan.get("improvement_tips", []):
        st.write(f"- {tip}")

    st.subheader("Rejected listings")
    rejected = final.get("rejected") or []
    if not rejected:
        st.caption("None rejected.")
    for item in rejected:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            opp, reason = item[0], item[1]
        else:
            opp, reason = item, ""
        label = opp.get("title", opp.get("id")) if isinstance(opp, dict) else opp
        st.write(f"❌ {label}: {reason}")

# ---------- keep polling while a run is active ----------
if ss.running:
    time.sleep(0.5)
    st.rerun()