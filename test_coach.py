
from datetime import date, timedelta

from agents.coach import (
    coach,
    detect_deadline_clash,
    generate_plan
)


def test_deadline_clash():

    today = date.today()

    opportunities = [
        {
            "id": "OP1",
            "deadline": str(today + timedelta(days=2)),
            "effort_hours": 5
        },
        {
            "id": "OP2",
            "deadline": str(today + timedelta(days=4)),
            "effort_hours": 6
        }
    ]

    result = detect_deadline_clash(opportunities, 8)

    assert result is not None
    assert result["ids"] == ["OP1", "OP2"]


def test_no_deadline_clash():

    opportunities = [
        {
            "id": "OP1",
            "deadline": str(date.today() + timedelta(days=2)),
            "effort_hours": 2
        },
        {
            "id": "OP2",
            "deadline": str(date.today() + timedelta(days=20)),
            "effort_hours": 3
        }
    ]

    result = detect_deadline_clash(opportunities, 8)

    assert result is None


def test_generate_plan():

    opportunities = [
        {
            "id": "OP1",
            "deadline": str(date.today() + timedelta(days=5)),
            "effort_hours": 4
        },
        {
            "id": "OP2",
            "deadline": str(date.today() + timedelta(days=10)),
            "effort_hours": 3
        }
    ]

    result = generate_plan(opportunities)

    assert len(result["ranked"]) == 2
    assert len(result["weekly_checklist"]) == 2
    assert len(result["improvement_tips"]) > 0


def test_empty_opportunities():

    state = {
        "verified": [],
        "candidates": [],
        "matches": [],
        "profile": {"weekly_hours": 10},
        "round_c": 1
    }

    result = coach(state)

    assert result["plan"]["ranked"] == []
    assert result["plan"]["weekly_checklist"] == []
