"""Coach agent: prioritize eligible opportunities and draft an action plan."""
from datetime import date
import json
import re

import config
import llm
from state import error_msg, make_msg

SENDER = "coach"
TOP_N = 3
CLASH_WINDOW_DAYS = 5
WEEKLY_CHECKLIST_PROMPT = """Create a concise application preparation plan from this data.
Return a JSON object with exactly these keys:
{"weekly_checklist": [{"week": 1, "tasks": ["..."]}],
 "improvement_tips": ["..."]}
Use 1-3 checklist weeks, with 1-4 actionable tasks per week. Tailor tasks to the
provided opportunities and profile gaps. Do not invent opportunity details or claim
that an application has been submitted. If there are no eligible matches, give useful
profile-improvement actions instead."""


def _msg(recipient: str, message_type: str, text: str) -> dict:
    return make_msg(SENDER, recipient, message_type, text)


def _as_number(value):
    try:
        if value is None or value == "":
            return None
        number = float(value)
        return number if number >= 0 else None
    except (TypeError, ValueError):
        return None


def _weekly_hours(state: dict):
    profile = state.get("profile") or {}
    for key in ("weekly_hours", "available_hours_per_week", "hours_per_week"):
        hours = _as_number(profile.get(key))
        if hours is not None:
            return hours

    text = str(state.get("student_input") or "")
    match = re.search(
        r"\b(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\s*(?:per\s*week|/week|weekly)\b",
        text,
        re.IGNORECASE,
    )
    return _as_number(match.group(1)) if match else None


def _today():
    return date.fromisoformat(config.TODAY)


def _days_until(deadline: str):
    if not isinstance(deadline, str) or deadline == "rolling":
        return None
    try:
        return (date.fromisoformat(deadline) - _today()).days
    except ValueError:
        return None


def _opportunities_by_id(state: dict) -> dict:
    records = {}
    for key in ("candidates", "verified"):
        for item in state.get(key) or []:
            if isinstance(item, dict) and item.get("id") is not None:
                records[str(item["id"])] = item
    return records


def _ranked_matches(state: dict):
    opportunities = _opportunities_by_id(state)
    ranked = []
    for match in state.get("matches") or []:
        if not isinstance(match, dict) or match.get("eligible") is not True:
            continue
        opportunity_id = match.get("opportunity_id")
        if opportunity_id is None:
            continue
        opportunity = opportunities.get(str(opportunity_id))
        if opportunity is None:
            continue

        deadline = opportunity.get("deadline") or "rolling"
        days = _days_until(deadline)
        effort = _as_number(opportunity.get("effort_hours"))
        match_score = _as_number(match.get("score"))

        urgency = 0.2 if days is None else max(0.0, 1.0 - min(max(days, 0), 30) / 30)
        effort_score = 0.5 if effort is None else 1.0 - min(effort, 40) / 40
        fit_score = min(match_score if match_score is not None else 0.0, 100.0) / 100
        priority = 0.45 * urgency + 0.35 * effort_score + 0.20 * fit_score

        ranked.append({
            "opportunity_id": str(opportunity_id),
            "title": str(opportunity.get("title") or "Opportunity"),
            "deadline": deadline,
            "days_until": days,
            "effort_hours": int(effort) if effort is not None and effort.is_integer() else effort,
            "score": int(match_score) if match_score is not None else 0,
            "priority": priority,
        })

    ranked.sort(key=lambda item: (
        -item["priority"],
        item["days_until"] is None,
        item["days_until"] if item["days_until"] is not None else float("inf"),
        item["effort_hours"] if item["effort_hours"] is not None else float("inf"),
        -item["score"],
        item["opportunity_id"],
    ))
    return ranked


def _clash(ranked: list, weekly_hours):
    if weekly_hours is None:
        return None
    choices = []
    for i, first in enumerate(ranked):
        first_days = first["days_until"]
        first_effort = first["effort_hours"]
        if first_days is None or first_days < 0 or first_effort is None:
            continue
        for second in ranked[i + 1:]:
            second_days = second["days_until"]
            second_effort = second["effort_hours"]
            if second_days is None or second_days < 0 or second_effort is None:
                continue
            gap = abs(first_days - second_days)
            combined_effort = first_effort + second_effort
            if gap <= CLASH_WINDOW_DAYS and combined_effort > weekly_hours:
                choices.append((gap, min(first_days, second_days), -combined_effort, first, second))
    if not choices:
        return None
    _, _, _, first, second = min(choices, key=lambda choice: choice[:3])
    return first, second


def _fallback_text(state: dict, ranked: list):
    profile = state.get("profile") or {}
    gaps = []
    for match in state.get("matches") or []:
        if not isinstance(match, dict) or match.get("eligible") is not True:
            continue
        for gap in match.get("gaps") or []:
            if isinstance(gap, dict) and gap.get("skill"):
                skill = str(gap["skill"])
                if skill not in gaps:
                    gaps.append(skill)

    if not ranked:
        notes = [
            str(reason)
            for match in (state.get("matches") or [])
            if isinstance(match, dict) and match.get("eligible") is False
            for reason in match.get("eligibility_reasons", [])
            if reason
        ]
        tips = []
        if notes:
            tips.append("Review the eligibility requirements noted in the match results before applying.")
        if profile.get("year") is None or profile.get("gpa") is None:
            tips.append("Add your current study year and GPA to your profile so eligibility can be assessed accurately.")
        if gaps:
            tips.append("Build evidence for relevant skills: " + ", ".join(gaps[:4]) + ".")
        if not tips:
            tips.append("Add relevant skills, projects, and interests to your profile to improve future matches.")
        checklist = [
            {"week": 1, "tasks": ["Review eligibility requirements and identify missing profile details."]},
            {"week": 2, "tasks": ["Choose one skill or project to strengthen for future opportunities."]},
        ]
        return checklist, tips

    first_title = ranked[0]["title"]
    checklist = [
        {"week": 1, "tasks": [
            f"Review the official requirements and gather application materials for {first_title}.",
            "Tailor your resume or profile to the opportunity requirements.",
        ]},
        {"week": 2, "tasks": [
            "Draft and review the application materials for your highest-priority opportunities.",
            "Submit applications before their listed deadlines and record confirmation.",
        ]},
    ]
    tips = ["Confirm each deadline and eligibility rule on the official opportunity page."]
    if gaps:
        tips.append("Strengthen relevant skill gaps: " + ", ".join(gaps[:4]) + ".")
    elif not profile.get("projects"):
        tips.append("Add a concise project example that demonstrates your relevant skills.")
    else:
        tips.append("Use a relevant project example to show how you applied your skills.")
    return checklist, tips


def _clean_generated_plan(result):
    if not isinstance(result, dict):
        return None
    checklist = result.get("weekly_checklist")
    tips = result.get("improvement_tips")
    if not isinstance(checklist, list) or not isinstance(tips, list):
        return None

    clean_checklist = []
    for index, week in enumerate(checklist[:3], start=1):
        if isinstance(week, dict):
            tasks = week.get("tasks")
            week_number = week.get("week", index)
        elif isinstance(week, str):
            tasks, week_number = [week], index
        else:
            continue
        if not isinstance(tasks, list):
            continue
        clean_tasks = [str(task).strip() for task in tasks if isinstance(task, str) and task.strip()]
        if clean_tasks:
            clean_checklist.append({"week": week_number, "tasks": clean_tasks[:4]})

    clean_tips = [str(tip).strip() for tip in tips if isinstance(tip, str) and tip.strip()][:5]
    return (clean_checklist, clean_tips) if clean_checklist and clean_tips else None


def _draft_text(state: dict, ranked: list):
    fallback = _fallback_text(state, ranked)
    profile = state.get("profile") or {}
    prompt_data = {
        "profile": {
            key: profile[key]
            for key in ("skills", "interests", "projects")
            if profile.get(key)
        },
        "eligible_opportunities": [
            {key: item[key] for key in ("opportunity_id", "title", "deadline", "effort_hours", "score")}
            for item in ranked[:TOP_N]
        ],
        "skill_gaps": [
            gap
            for match in (state.get("matches") or [])
            if isinstance(match, dict) and match.get("eligible") is True
            for gap in (match.get("gaps") or [])
            if isinstance(gap, dict)
        ][:12],
    }
    try:
        result, provider = llm.ask(json.dumps(prompt_data), system=WEEKLY_CHECKLIST_PROMPT, want_json=True)
        cleaned = _clean_generated_plan(result)
        if cleaned:
            return cleaned, provider
        reason = "invalid response" if result is not None else "provider unavailable"
        return fallback, f"fallback: {reason} ({provider})"
    except Exception as exc:
        return fallback, f"fallback: LLM drafting failed ({exc})"


def _plan_ranked(ranked: list) -> list:
    output = []
    for rank, item in enumerate(ranked[:TOP_N], start=1):
        days = item["days_until"]
        deadline_reason = (
            "rolling deadline" if item["deadline"] == "rolling"
            else f"deadline in {days} day(s)" if days is not None
            else f"listed deadline {item['deadline']}"
        )
        effort = (
            f"about {item['effort_hours']} effort hour(s)"
            if item["effort_hours"] is not None else "effort not specified"
        )
        output.append({
            "opportunity_id": item["opportunity_id"],
            "rank": rank,
            "deadline": item["deadline"],
            "why": f"Prioritized by {deadline_reason}, {effort}, and fit score {item['score']}/100.",
            "effort_hours": item["effort_hours"] if item["effort_hours"] is not None else 0,
        })
    return output


def run(state: dict) -> dict:
    """Return a ranked plan and optional one-time Matcher challenge."""
    messages = []
    try:
        ranked = _ranked_matches(state)
        weekly_hours = _weekly_hours(state)
        challenge = None

        if not ranked:
            messages.append(_msg(
                "all", "info",
                "No eligible verified opportunities are available; the plan focuses on improving the profile.",
            ))
        elif weekly_hours is None:
            messages.append(_msg(
                "all", "info",
                "Weekly availability was not provided, so deadline clashes could not be assessed.",
            ))

        clash = _clash(ranked, weekly_hours)
        if clash and state.get("round_c", 0) < config.MAX_COACH_ROUNDS and not state.get("challenge"):
            first, second = clash
            combined_effort = first["effort_hours"] + second["effort_hours"]
            reason = (
                f"{first['title']} and {second['title']} have deadlines within "
                f"{CLASH_WINDOW_DAYS} days and require {combined_effort} effort hours combined, "
                f"above the student's {weekly_hours:g} available hours per week."
            )
            challenge = {"ids": [first["opportunity_id"], second["opportunity_id"]], "reason": reason}
            messages.append(_msg("matcher", "challenge", reason))

        ranked_plan = _plan_ranked(ranked)
        (checklist, tips), provider = _draft_text(state, ranked)
        plan = {
            "ranked": ranked_plan,
            "weekly_checklist": checklist,
            "improvement_tips": tips,
        }

        if provider and provider.startswith("fallback:"):
            messages.append(_msg("all", "info", f"AI plan writing unavailable; used a code fallback ({provider})."))
        elif provider:
            messages.append(_msg("all", "info", f"AI plan text drafted using {provider}."))
        messages.append(_msg(
            "all", "result",
            f"Prepared a plan with {len(ranked_plan)} ranked eligible opportunity(ies).",
        ))
        return {"plan": plan, "challenge": challenge, "messages": messages}
    except Exception as exc:
        messages.append(error_msg(SENDER, f"Coach failed: {str(exc)[:160]}. Returning an empty plan."))
        return {
            "plan": {"ranked": [], "weekly_checklist": [], "improvement_tips": []},
            "challenge": None,
            "messages": messages,
        }


coach = run