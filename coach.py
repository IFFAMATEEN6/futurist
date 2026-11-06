
from datetime import date, datetime


MAX_CLASH_DAYS = 5
MAX_COACH_ROUNDS = 1


def parse_date(deadline):
    """Convert deadline into date format."""

    if isinstance(deadline, date):
        return deadline

    if not deadline:
        return None

    try:
        return datetime.fromisoformat(str(deadline)).date()
    except ValueError:
        return None


def get_eligible_opportunities(state):
    """Get eligible opportunities from Matcher results."""

    opportunities = (
        state.get("verified")
        or state.get("candidates")
        or []
    )

    opportunity_map = {
        item["id"]: item
        for item in opportunities
        if isinstance(item, dict) and item.get("id")
    }

    matches = state.get("matches") or []

    eligible_opportunities = []

    for match in matches:

        if not isinstance(match, dict):
            continue

        if not match.get("eligible", False):
            continue

        opportunity_id = match.get("opportunity_id")

        opportunity = opportunity_map.get(opportunity_id)

        if opportunity:
            combined = {**opportunity, **match}
            eligible_opportunities.append(combined)

    return eligible_opportunities


def detect_deadline_clash(opportunities, weekly_hours):
    """Detect deadline clashes within five days."""

    for first_index in range(len(opportunities)):

        for second_index in range(first_index + 1, len(opportunities)):

            first = opportunities[first_index]
            second = opportunities[second_index]

            first_deadline = parse_date(first.get("deadline"))
            second_deadline = parse_date(second.get("deadline"))

            if not first_deadline or not second_deadline:
                continue

            days_apart = abs(
                (first_deadline - second_deadline).days
            )

            first_effort = float(first.get("effort_hours", 0))
            second_effort = float(second.get("effort_hours", 0))

            total_effort = first_effort + second_effort

            if (
                days_apart <= MAX_CLASH_DAYS
                and total_effort > weekly_hours
            ):

                return {
                    "ids": [
                        first.get("id"),
                        second.get("id")
                    ],
                    "reason": (
                        f"Deadline clash detected. "
                        f"Both deadlines are {days_apart} days apart. "
                        f"Required effort: {total_effort} hours. "
                        f"Available weekly hours: {weekly_hours}."
                    )
                }

    return None


def generate_plan(opportunities):
    """Generate ranked opportunities and weekly checklist."""

    today = date.today()

    ranked = []

    for opportunity in opportunities:

        deadline = parse_date(opportunity.get("deadline"))

        if deadline is None:
            continue

        days_left = (deadline - today).days

        effort = float(
            opportunity.get("effort_hours", 0)
        )

        score = 100 - (max(days_left, 0) * 2) - effort

        ranked.append({
            "opportunity_id": opportunity.get("id"),
            "rank": 0,
            "deadline": str(deadline),
            "effort_hours": effort,
            "why": (
                f"Deadline is in {days_left} days. "
                f"Estimated effort is {effort} hours."
            ),
            "score": score
        })

    ranked.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    for rank, opportunity in enumerate(ranked, start=1):
        opportunity["rank"] = rank

    weekly_checklist = []

    for opportunity in ranked:

        weekly_checklist.append({
            "week": 1,
            "tasks": [
                f"Prepare application for "
                f"{opportunity['opportunity_id']}",
                f"Complete work before "
                f"{opportunity['deadline']}"
            ]
        })

    improvement_tips = [
        "Keep your CV updated.",
        "Improve skills required by your target opportunities.",
        "Build practical projects for your portfolio.",
        "Start applications before their deadlines."
    ]

    return {
        "ranked": ranked,
        "weekly_checklist": weekly_checklist,
        "improvement_tips": improvement_tips
    }


def coach(state):
    """Main Coach Agent."""

    opportunities = get_eligible_opportunities(state)

    profile = state.get("profile") or {}

    weekly_hours = float(
        profile.get("weekly_hours")
        or profile.get("available_hours_per_week")
        or 10
    )

    round_c = state.get("round_c", 0)

    # Challenge Matcher only once.
    if round_c < MAX_COACH_ROUNDS:

        challenge = detect_deadline_clash(
            opportunities,
            weekly_hours
        )

        if challenge:

            return {
                "challenge": challenge,
                "round_c": round_c + 1,
                "messages": [{
                    "sender": "coach",
                    "recipient": "matcher",
                    "type": "challenge",
                    "text": challenge["reason"]
                }]
            }

    # Generate final plan.
    plan = generate_plan(opportunities)

    return {
        "plan": plan,
        "challenge": None,
        "messages": [{
            "sender": "coach",
            "recipient": "user",
            "type": "result",
            "text": "Your final opportunity plan is ready."
        }]
    }


agent = coach
run = coach
