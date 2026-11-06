"""Smoke tests for the application."""

import pytest
import json
from datetime import date, datetime

STUDENT_A = """
Name: Ahmed Ali
Year: 3
Field: Computer Science
GPA: 3.3
Skills: Python, basic machine learning, HTML
Projects: One class project — student grade tracker
Interests: AI internships, scholarships
"""


def _load_graph():
    """Returns run_graph or skips the test cleanly."""
    try:
        from graph import run_graph
        return run_graph
    except ImportError:
        pytest.skip("graph.py not on main yet — waiting for Iffa's merge")


class TestFullPipeline:

    def test_pipeline_does_not_crash(self):
        run_graph = _load_graph()
        result = run_graph(STUDENT_A)
        assert result is not None

    def test_planted_expired_rejected(self):
        run_graph = _load_graph()
        result = run_graph(STUDENT_A)
        ids = [r["id"] for r in result.get("rejected", [])]
        assert "opp_m2_planted_expired" in ids, \
            "Expired planted listing was NOT rejected — Verifier broken"

    def test_planted_fee_rejected(self):
        run_graph = _load_graph()
        result = run_graph(STUDENT_A)
        ids = [r["id"] for r in result.get("rejected", [])]
        assert "opp_m2_planted_fee" in ids, \
            "Fee-charging planted listing was NOT rejected — Verifier broken"

    def test_message_log_non_empty(self):
        run_graph = _load_graph()
        result = run_graph(STUDENT_A)
        assert len(result.get("messages", [])) > 0

    def test_no_verified_listing_is_expired(self):
        run_graph = _load_graph()
        result = run_graph(STUDENT_A)
        with open("data/opportunities.json") as f:
            opp_map = {o["id"]: o for o in json.load(f)}
        today = date.today()
        for opp_id in result.get("verified", []):
            opp = opp_map.get(opp_id, {})
            dl  = opp.get("deadline", "rolling")
            if dl != "rolling":
                dl_date = datetime.strptime(dl, "%Y-%m-%d").date()
                assert dl_date >= today, \
                    f"Verified listing {opp_id} has expired deadline {dl}"

    def test_no_verified_listing_has_fee(self):
        run_graph = _load_graph()
        result = run_graph(STUDENT_A)
        with open("data/opportunities.json") as f:
            opp_map = {o["id"]: o for o in json.load(f)}
        for opp_id in result.get("verified", []):
            opp = opp_map.get(opp_id, {})
            assert opp.get("application_fee") is not True, \
                f"Verified listing {opp_id} charges a fee — should have been rejected"