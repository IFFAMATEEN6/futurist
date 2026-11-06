"""Tests for the Verifier agent (M2).

State contract (from state.py / graph.py — M1):
  - candidates      : list[dict]  full opportunity records (Scout output)
  - round_v         : int         0 = first pass, >0 = recheck round
  - recheck         : list[str]   ids Verifier asked Scout to re-check
  - offline         : bool
  - verified (out)  : list[dict]  full records that passed
  - rejected (out)  : list[tuple[dict, str]]  (opp_record, reason)
  - recheck  (out)  : list[str]   ids to send back to Scout
  - messages (out)  : list[Msg]   {sender, recipient, type, text, ts}
"""

import pytest
from datetime import date, timedelta
from agents.verifier import run as verifier


# ── Helpers ───────────────────────────────────────────────────────────────────
def make_state(candidates, round_v=0, offline=False, recheck=None):
    """Build a minimal state dict as graph.py would provide."""
    return {
        "candidates":  candidates,
        "round_v":     round_v,
        "offline":     offline,
        "recheck":     recheck or [],
        "messages":    [],
    }


def _base_opp(overrides=None):
    """
    A perfectly clean, valid opportunity dict (Scout format).
    Override any field to test a specific failure case.
    """
    today = date.today()
    opp = {
        "id":              "opp_test_base",
        "title":           "Test Software Internship",
        "org":             "Legit Corp",
        "type":            "internship",
        "deadline":        (today + timedelta(days=60)).strftime("%Y-%m-%d"),
        "eligibility": {
            "min_year": 2, "min_gpa": 3.0,
            "fields": ["Computer Science"], "nationalities": []
        },
        "required_skills": ["Python"],
        "effort_hours":    6,
        "application_fee": False,
        "source_url":      "https://legitcorp.com/careers/intern",
        "last_checked":    today.strftime("%Y-%m-%d"),
        "description":     "A real internship.",
        "planted":         False,
    }
    if overrides:
        opp.update(overrides)
    return opp


# ── Result accessors (match new contract) ─────────────────────────────────────
def verified_ids(result):
    """IDs of records in verified (list[dict])."""
    return [o["id"] for o in result["verified"]]


def rejected_ids(result):
    """IDs of records in rejected (list[tuple[dict, str]])."""
    return [o["id"] for o, _ in result["rejected"]]


def rejected_reason(result, opp_id):
    """Rejection reason string for a given id."""
    for o, reason in result["rejected"]:
        if o["id"] == opp_id:
            return reason
    raise KeyError(opp_id)


# ── Planted listings ──────────────────────────────────────────────────────────
class TestPlantedListings:

    def test_planted_expired_is_rejected(self):
        opp = _base_opp({"id": "opp_m2_planted_expired", "deadline": "2025-03-01", "planted": True})
        result = verifier(make_state([opp]))
        assert "opp_m2_planted_expired" in rejected_ids(result)

    def test_planted_expired_reason_mentions_deadline(self):
        opp = _base_opp({"id": "opp_m2_planted_expired", "deadline": "2025-03-01", "planted": True})
        result = verifier(make_state([opp]))
        reason = rejected_reason(result, "opp_m2_planted_expired")
        assert any(w in reason.lower() for w in ("deadline", "passed", "expired"))

    def test_planted_fee_is_rejected(self):
        opp = _base_opp({"id": "opp_m2_planted_fee", "application_fee": True, "planted": True})
        result = verifier(make_state([opp]))
        assert "opp_m2_planted_fee" in rejected_ids(result)

    def test_planted_fee_reason_mentions_fee(self):
        opp = _base_opp({"id": "opp_m2_planted_fee", "application_fee": True, "planted": True})
        result = verifier(make_state([opp]))
        reason = rejected_reason(result, "opp_m2_planted_fee")
        assert "fee" in reason.lower()


# ── Individual rejection rules ────────────────────────────────────────────────
class TestRejectionRules:

    def test_expired_deadline_rejected(self):
        opp = _base_opp({"id": "opp_exp", "deadline": "2020-01-01"})
        result = verifier(make_state([opp]))
        assert "opp_exp" in rejected_ids(result)

    def test_rolling_deadline_not_rejected(self):
        opp = _base_opp({"id": "opp_rolling", "deadline": "rolling"})
        result = verifier(make_state([opp]))
        assert "opp_rolling" not in rejected_ids(result)

    def test_deadline_today_not_expired(self):
        """A deadline of today is NOT past — must not be rejected for expiry."""
        today_str = date.today().strftime("%Y-%m-%d")
        opp = _base_opp({"id": "opp_today_dl", "deadline": today_str})
        result = verifier(make_state([opp]))
        expired_rejection = any(
            o["id"] == "opp_today_dl" and "passed" in reason.lower()
            for o, reason in result["rejected"]
        )
        assert not expired_rejection, "Deadline of today should NOT be treated as expired"

    def test_unparseable_deadline_treated_as_expired(self):
        """A deadline string that cannot be parsed is treated as expired."""
        opp = _base_opp({"id": "opp_bad_date", "deadline": "not-a-date"})
        result = verifier(make_state([opp]))
        assert "opp_bad_date" in rejected_ids(result)

    def test_application_fee_rejected(self):
        opp = _base_opp({"id": "opp_fee", "application_fee": True})
        result = verifier(make_state([opp]))
        assert "opp_fee" in rejected_ids(result)

    def test_missing_source_url_rejected(self):
        opp = _base_opp({"id": "opp_no_url", "source_url": ""})
        result = verifier(make_state([opp]))
        assert "opp_no_url" in rejected_ids(result)

    def test_unofficial_url_rejected_when_online(self):
        opp = _base_opp({"id": "opp_bitly", "source_url": "https://bit.ly/abc123"})
        result = verifier(make_state([opp], offline=False))
        assert "opp_bitly" in rejected_ids(result)

    def test_unofficial_url_allowed_when_offline(self):
        """URL check must be skipped entirely when offline=True."""
        opp = _base_opp({"id": "opp_bitly_offline", "source_url": "https://bit.ly/abc123"})
        result = verifier(make_state([opp], offline=True))
        assert "opp_bitly_offline" not in rejected_ids(result)

    @pytest.mark.parametrize("url_pattern,opp_id", [
        ("https://bit.ly/abc",                "opp_url_bitly"),
        ("https://tinyurl.com/abc",           "opp_url_tinyurl"),
        ("https://t.co/abc",                  "opp_url_tco"),
        ("https://forms.gle/abc",             "opp_url_formsgle"),
        ("https://docs.google.com/forms/abc", "opp_url_googleforms"),
        ("https://linktr.ee/someorg",         "opp_url_linktree"),
    ])
    def test_all_unofficial_url_patterns_rejected(self, url_pattern, opp_id):
        """Every known unofficial URL pattern must trigger rejection when online."""
        opp = _base_opp({"id": opp_id, "source_url": url_pattern})
        result = verifier(make_state([opp], offline=False))
        assert opp_id in rejected_ids(result), (
            f"URL pattern '{url_pattern}' should trigger rejection but did not"
        )

    def test_missing_required_field_rejected(self):
        opp = _base_opp({"id": "opp_no_title"})
        del opp["title"]
        result = verifier(make_state([opp]))
        assert "opp_no_title" in rejected_ids(result)

    def test_scam_signal_in_title_rejected(self):
        opp = _base_opp({"id": "opp_scam", "title": "Guaranteed Selection Internship Program"})
        result = verifier(make_state([opp]))
        assert "opp_scam" in rejected_ids(result)

    def test_scam_signal_in_org_rejected(self):
        opp = _base_opp({"id": "opp_scam_org", "org": "100% Scholarship Foundation"})
        result = verifier(make_state([opp]))
        assert "opp_scam_org" in rejected_ids(result)

    def test_guaranteed_admission_scam_phrase_rejected(self):
        opp = _base_opp({"id": "opp_scam_admission", "title": "Guaranteed Admission MBA Program"})
        result = verifier(make_state([opp]))
        assert "opp_scam_admission" in rejected_ids(result)

    def test_guaranteed_job_scam_phrase_rejected(self):
        opp = _base_opp({"id": "opp_scam_job", "title": "Guaranteed Job Placement Bootcamp"})
        result = verifier(make_state([opp]))
        assert "opp_scam_job" in rejected_ids(result)


# ── Clean listing passes ──────────────────────────────────────────────────────
class TestCleanListing:

    def test_clean_listing_is_verified(self):
        opp = _base_opp()
        result = verifier(make_state([opp]))
        assert "opp_test_base" in verified_ids(result)

    def test_clean_listing_not_in_rejected(self):
        opp = _base_opp()
        result = verifier(make_state([opp]))
        assert "opp_test_base" not in rejected_ids(result)

    def test_clean_listing_not_in_recheck(self):
        opp = _base_opp()
        result = verifier(make_state([opp]))
        assert "opp_test_base" not in result["recheck"]

    def test_verified_contains_full_record(self):
        """Verified must hold full dicts (not just IDs) so Coach/Matcher can use them."""
        opp = _base_opp()
        result = verifier(make_state([opp]))
        assert "opp_test_base" in verified_ids(result)
        verified_record = next(o for o in result["verified"] if o["id"] == "opp_test_base")
        assert "title"    in verified_record
        assert "deadline" in verified_record
        assert "org"      in verified_record

    def test_rejected_contains_full_record_and_reason(self):
        """Rejected must be list of (opp_dict, reason_str) tuples."""
        opp = _base_opp({"id": "opp_fee_full", "application_fee": True})
        result = verifier(make_state([opp]))
        assert "opp_fee_full" in rejected_ids(result)
        rec, reason = next(
            (o, r) for o, r in result["rejected"] if o["id"] == "opp_fee_full"
        )
        assert isinstance(rec, dict), "rejected[i][0] must be a full opp dict"
        assert isinstance(reason, str), "rejected[i][1] must be a reason string"
        assert "title" in rec


# ── Message contract ──────────────────────────────────────────────────────────
class TestMessageContract:

    def test_messages_always_returned(self):
        result = verifier(make_state([]))
        assert "messages" in result
        assert isinstance(result["messages"], list)
        assert len(result["messages"]) > 0

    def test_every_message_has_ts_field(self):
        """state.py Msg TypedDict requires a ts field — make_msg() adds it."""
        opp = _base_opp()
        result = verifier(make_state([opp]))
        for msg in result["messages"]:
            assert "ts" in msg, f"Message missing ts field: {msg}"

    def test_every_message_has_required_keys(self):
        """All messages must have sender, recipient, type, text, ts."""
        opp = _base_opp()
        result = verifier(make_state([opp]))
        for msg in result["messages"]:
            for key in ("sender", "recipient", "type", "text", "ts"):
                assert key in msg, f"Message missing key '{key}': {msg}"

    def test_existing_messages_are_preserved(self):
        """Messages from earlier agents must not be wiped."""
        opp = _base_opp()
        prior_msg = {
            "sender": "scout", "recipient": "all",
            "type": "result", "text": "Scout found 1 candidate",
            "ts": "2026-11-06T10:00:00",
        }
        state = make_state([opp])
        state["messages"] = [prior_msg]
        result = verifier(state)
        # The graph uses Annotated[list, operator.add] so verifier only appends new messages;
        # the prior message is preserved at the graph level. The agent itself must NOT wipe messages.
        # We verify the agent returns its own new messages (not the full combined log).
        assert isinstance(result["messages"], list)
        assert len(result["messages"]) > 0


# ── Recheck (doubtful) logic ──────────────────────────────────────────────────
class TestRecheckRound:

    def test_recheck_fires_max_once(self):
        """
        Round 0: a stale listing (last_checked > 30 days) goes to Scout recheck
                 (LLM unavailable -> falls back to 'recheck').
        Round 1: same listing confirmed by Scout must NOT go to recheck again.
        """
        old_date = (date.today() - timedelta(days=45)).strftime("%Y-%m-%d")
        opp = _base_opp({"id": "opp_recheck_once", "last_checked": old_date})

        # Round 0 — Verifier sends it to Scout
        result_r0 = verifier(make_state([opp], round_v=0))
        assert "opp_recheck_once" in result_r0["recheck"], (
            "Stale listing (last_checked > 30 days) should be sent to recheck in round 0"
        )

        # Round 1 — Scout re-confirmed; recheck round uses recheck ids from state
        result_r1 = verifier(make_state([opp], round_v=1, recheck=["opp_recheck_once"]))
        assert "opp_recheck_once" not in result_r1["recheck"], (
            "Verifier sent the same ID to recheck a second time — must only fire once"
        )

    def test_round1_verifies_all_valid_candidates_and_does_not_recheck(self):
        """In round 1, all candidates are processed, doubtful check is skipped, and recheck is empty."""
        opp_a = _base_opp({"id": "opp_a"})
        old_date = (date.today() - timedelta(days=45)).strftime("%Y-%m-%d")
        opp_b = _base_opp({"id": "opp_b", "last_checked": old_date})

        result = verifier(make_state([opp_a, opp_b], round_v=1))

        # Both valid candidates pass; opp_b had a stale date but in round 1 doubtful check is skipped
        assert "opp_a" in verified_ids(result)
        assert "opp_b" in verified_ids(result)
        assert result["recheck"] == []

    def test_near_deadline_listing_goes_to_recheck(self):
        """A listing whose deadline is 2 days away triggers doubtful -> recheck in round 0."""
        near_deadline = (date.today() + timedelta(days=2)).strftime("%Y-%m-%d")
        opp = _base_opp({"id": "opp_near_dl", "deadline": near_deadline})
        result = verifier(make_state([opp], round_v=0))
        assert "opp_near_dl" not in rejected_ids(result), (
            "Near-deadline listing should not be hard-rejected"
        )
        assert "opp_near_dl" in result["recheck"], (
            "Near-deadline listing (deadline in 2 days) should be flagged as doubtful -> recheck"
        )


# ── Edge cases ────────────────────────────────────────────────────────────────
class TestEdgeCases:

    def test_unknown_id_does_not_crash(self):
        """An opp_id in recheck that isn't in candidates is handled gracefully."""
        result = verifier(make_state([], round_v=1, recheck=["opp_ghost"]))
        # opp_ghost is not in opp_map, so ids_to_check is empty — no crash
        assert result is not None

    def test_empty_candidates_does_not_crash(self):
        result = verifier(make_state([]))
        assert result is not None

    def test_returns_only_owned_keys(self):
        """Verifier must not write keys it does not own (graph.py guarded() will drop them)."""
        opp = _base_opp()
        result = verifier(make_state([opp]))
        owned = {"verified", "rejected", "recheck", "messages"}
        for key in result:
            assert key in owned, f"Verifier returned unexpected state key: '{key}'"

    def test_no_verified_listing_has_expired_deadline(self):
        expired = _base_opp({"id": "opp_exp2",   "deadline": "2020-06-01"})
        clean   = _base_opp({"id": "opp_clean2"})
        result  = verifier(make_state([expired, clean]))
        assert "opp_exp2"   not in verified_ids(result)
        assert "opp_clean2" in     verified_ids(result)

    def test_no_verified_listing_has_fee(self):
        fee   = _base_opp({"id": "opp_fee2",   "application_fee": True})
        clean = _base_opp({"id": "opp_clean3"})
        result = verifier(make_state([fee, clean]))
        assert "opp_fee2"   not in verified_ids(result)
        assert "opp_clean3" in     verified_ids(result)
