"""Prioritize matches and build a deterministic, capacity-bounded preparation schedule.

Extends the team's Coach implementation with explicit conditional matches, scheduling,
deadline deferrals, and optional prose assistance that cannot alter factual decisions.
"""
import json
import re
from datetime import date, timedelta

import config
import llm
from domain import number, today
from state import make_msg

TOP_N = 3
CLASH_WINDOW_DAYS = 5
HORIZON_DAYS = 28


def _msg(recipient, kind, text):
    return make_msg("coach", recipient, kind, text)


def _weekly_hours(state):
    values = [state.get("weekly_hours")]
    profile = state.get("profile") or {}
    values += [profile.get(key) for key in ("weekly_hours", "available_hours_per_week", "hours_per_week")]
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\s*(?:per\s*week|/week|weekly)\b",
                      str(state.get("student_input", "")), re.I)
    if match:
        values.append(match.group(1))
    return next((n for value in values if (n := number(value)) is not None and 0 <= n <= 80), None)


def _ranked_matches(state):
    records = {o["id"]: o for o in state.get("verified", []) if isinstance(o, dict) and o.get("id")}
    ranked, seen = [], set()
    for match in state.get("matches") or []:
        oid = match.get("opportunity_id")
        status = match.get("eligibility_status", "eligible" if match.get("eligible") else "ineligible")
        if status == "ineligible" or oid not in records or oid in seen:
            continue
        seen.add(oid)
        opp = records[oid]
        deadline = opp.get("deadline", "rolling")
        try:
            days = None if deadline == "rolling" else (date.fromisoformat(deadline) - today()).days
        except (ValueError, TypeError):
            continue
        if days is not None and days < 0:
            continue
        effort = number(opp.get("effort_hours"))
        if effort is None or effort < 0:
            continue
        fit = min(100, max(0, number(match.get("score")) or 0))
        urgency = 0.2 if days is None else max(0, 1 - min(days, 30) / 30)
        priority = 0.45 * urgency + 0.35 * (1 - min(effort, 40) / 40) + 0.2 * fit / 100
        ranked.append({"opportunity_id": oid, "title": opp.get("title", oid), "deadline": deadline,
                       "days_until": days, "effort_hours": effort, "score": int(fit), "priority": priority,
                       "eligibility_status": status, "source_url": opp.get("source_url", ""),
                       "type": opp.get("type", "opportunity"), "eligibility_reasons": match.get("eligibility_reasons", []),
                       "gaps": match.get("gaps", [])})
    return sorted(ranked, key=lambda item: (-item["priority"], item["days_until"] is None,
                  item["days_until"] if item["days_until"] is not None else 10000, item["opportunity_id"]))


def _clash(ranked, weekly_hours):
    if weekly_hours is None:
        return None
    for i, first in enumerate(ranked[:6]):
        for second in ranked[i + 1:6]:
            a, b = first["days_until"], second["days_until"]
            if a is not None and b is not None and abs(a - b) <= CLASH_WINDOW_DAYS:
                if first["effort_hours"] + second["effort_hours"] > weekly_hours:
                    return first, second
    return None


def _due_days(item):
    return min(HORIZON_DAYS, max(1, item["days_until"] + 1)) if item["days_until"] is not None else HORIZON_DAYS


def _fits(items, weekly_hours):
    total = 0
    for item in sorted(items, key=_due_days):
        total += item["effort_hours"]
        if total > _due_days(item) * weekly_hours / 7 + 1e-8:
            return False
    return True


def _schedule(selected, weekly_hours):
    """Allocate at a constant daily capacity, never after a listed deadline."""
    slots = [weekly_hours / 7] * HORIZON_DAYS
    allocations, end_days = {}, {}
    for item in sorted(selected, key=_due_days):
        remaining = item["effort_hours"]
        for day in range(_due_days(item)):
            amount = min(remaining, slots[day])
            if amount <= 1e-8:
                continue
            slots[day] -= amount
            remaining -= amount
            key = (day // 7 + 1, item["opportunity_id"])
            allocations[key] = allocations.get(key, 0) + amount
            end_days[key] = day
            if remaining <= 1e-8:
                break
    weeks = []
    by_id = {item["opportunity_id"]: item for item in selected}
    for week in range(1, 5):
        records = [(oid, amount) for (w, oid), amount in allocations.items() if w == week]
        if not records:
            continue
        tasks, rows = [], []
        for oid, amount in records:
            item = by_id[oid]
            action = ("confirm rules, prepare a project and submission materials" if item["type"] in ("hackathon", "competition")
                      else "confirm eligibility, tailor your resume and prepare application materials")
            deadline = "rolling applications" if item["deadline"] == "rolling" else f"deadline {item['deadline']}"
            finish = (today() + timedelta(days=end_days[(week, oid)])).isoformat()
            tasks.append(f"{item['title']}: {action} ({amount:.1f} h this week; finish this step by {finish}; {deadline}).")
            rows.append({"opportunity_id": oid, "hours": round(amount, 4), "last_preparation_date": finish})
        weeks.append({"week": week, "starts": (today() + timedelta(days=(week - 1) * 7)).isoformat(),
                      "hours": round(sum(amount for _, amount in records), 4), "tasks": tasks,
                      "allocations": rows})
    return weeks


def _tips(state, ranked):
    tips = ["Confirm current deadlines, fees and full eligibility on each source page before applying."]
    gaps = list(dict.fromkeys(gap["skill"] for item in ranked for gap in item["gaps"] if gap.get("skill")))
    if gaps:
        tips.append("Build evidence for your priority skill gaps: " + ", ".join(gaps[:4]) + ". Use the learning links in your matches.")
    profile = state.get("profile") or {}
    if profile.get("missing_fields"):
        tips.append("Complete your profile: " + ", ".join(profile["missing_fields"]) + ".")
    if not profile.get("projects"):
        tips.append("Add one project with your role, the tools used and a measurable outcome.")
    return tips


def run(state):
    if not isinstance(state, dict):
        return {"plan": {"ranked": [], "weekly_checklist": [], "improvement_tips": []}, "challenge": None,
                "messages": [_msg("all", "error", "Coach needs a valid workflow state.")]}
    ranked = _ranked_matches(state)
    capacity = _weekly_hours(state)
    messages, challenge = [], None
    clash = _clash(ranked, capacity)
    if clash and state.get("round_c", 0) < config.MAX_COACH_ROUNDS and not state.get("challenge"):
        first, second = clash
        combined = first["effort_hours"] + second["effort_hours"]
        reason = (f"{first['title']} and {second['title']} have deadlines within {CLASH_WINDOW_DAYS} days and need "
                  f"{combined:g} effort hours combined, above {capacity:g} available hours per week. "
                  "Prioritize the stronger practical fit; the final schedule will respect actual time available.")
        challenge = {"ids": [first["opportunity_id"], second["opportunity_id"]],
                     "preferred_id": first["opportunity_id"], "reason": reason}
        messages.append(_msg("matcher", "challenge", reason))
    selected, deferred = [], []
    for item in ranked:
        if len(selected) >= TOP_N:
            break
        if capacity is None or _fits(selected + [item], capacity):
            selected.append(item)
        else:
            deferred.append({"opportunity_id": item["opportunity_id"], "title": item["title"],
                             "reason": "Preparation does not fit your available hours before the deadline within the four-week plan."})
    plan_ranked = []
    for rank, item in enumerate(selected, 1):
        conditional = "Confirm full eligibility first. " if item["eligibility_status"] == "conditional" else ""
        plan_ranked.append({**item, "rank": rank,
                            "why": f"{conditional}Fit {item['score']}/100, {item['effort_hours']:g} estimated preparation hours; "
                                   f"{'rolling deadline' if item['days_until'] is None else str(item['days_until']) + ' days until deadline'}."})
    tips = _tips(state, selected)
    if state.get("use_llm"):
        result, note = llm.ask(json.dumps({"skills": (state.get("profile") or {}).get("skills", []),
                                         "gaps": [g["skill"] for item in selected for g in item["gaps"]]}),
                               system="Suggest up to three concise study tips as JSON {\"improvement_tips\":[...]}. Do not invent qualifications, opportunities, deadlines, or change a schedule.",
                               want_json=True)
        additions = result.get("improvement_tips") if isinstance(result, dict) else None
        if isinstance(additions, list) and any(isinstance(t, str) and t.strip() for t in additions):
            tips += [t.strip()[:400] for t in additions if isinstance(t, str) and t.strip()][:3]
            messages.append(_msg("all", "info", f"Optional study suggestions drafted with {note}; ranking and scheduling remain rule-based."))
        else:
            messages.append(_msg("all", "info", "Optional language assistance unavailable; used the local planning rules."))
    checklist = _schedule(selected, capacity) if selected and capacity is not None else []
    if not selected:
        checklist = [{"week": 1, "hours": 0, "tasks": ["Review missing profile details and eligibility requirements before choosing an application."]}]
    if capacity is None:
        messages.append(_msg("all", "info", "Weekly availability was not provided; ranking is available but no capacity-based schedule was invented."))
    if deferred:
        tips.append(f"{len(deferred)} match(es) were deferred because preparation exceeds the time available. Review them before increasing your commitment.")
    plan = {"ranked": plan_ranked, "weekly_checklist": checklist, "improvement_tips": tips,
            "deferred": deferred, "weekly_hours": capacity, "planning_date": config.TODAY,
            "total_hours": sum(item["effort_hours"] for item in selected)}
    messages.append(_msg("all", "result", f"Prepared {len(selected)} priorities and {len(checklist)} checklist week(s); "
                         f"{len(deferred)} deferred. Conditional matches begin with source and eligibility confirmation."))
    return {"plan": plan, "challenge": challenge, "messages": messages}


coach = run
