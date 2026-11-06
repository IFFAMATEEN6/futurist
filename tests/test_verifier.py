"""Tests for the Verifier agent."""


import pytest
from datetime import date, timedelta
from agents.verifier import verifier


# ── Helpers ───────────────────────────────────────────────────────────────────
def make_state(candidates, opportunities,
               round_v=0, offline=False, recheck_responses=None):
    return {
        "candidates":        candidates,
        "_opportunities":    opportunities,
        "round_v":           round_v,
        "offline":           offline,
        "recheck_responses": recheck_responses or [],
        "messages":          [],
    }


def _base_opp(overrides=None):
    """
    A perfectly clean, valid opportunity.
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
        "planted":         False,
    }
    if overrides:
        opp.update(overrides)
    return opp


def get_rejected_ids(result):
    return [r["id"] for r in result["rejected"]]


# ── Planted listings ──────────────────────────────────────────────────────────
class TestPlantedListings:

    def test_planted_expired_is_rejected(self):
        opp = _base_opp({
            "id":       "opp_m2_planted_expired",
            "deadline": "2025-03-01",
            "planted":  True
        })
        result = verifier(make_state(["opp_m2_planted_expired"], [opp]))
        assert "opp_m2_planted_expired" in get_rejected_ids(result)

    def test_planted_expired_reason_mentions_deadline(self):
        opp = _base_opp({
            "id":       "opp_m2_planted_expired",
            "deadline": "2025-03-01",
            "planted":  True
        })
        result = verifier(make_state(["opp_m2_planted_expired"], [opp]))
        reason = next(
            r["reason"] for r in result["rejected"]
            if r["id"] == "opp_m2_planted_expired"
        )
        assert any(w in reason.lower() for w in ("deadline", "passed", "expired"))

    def test_planted_fee_is_rejected(self):
        opp = _base_opp({
            "id":               "opp_m2_planted_fee",
            "application_fee":  True,
            "planted":          True
        })
        result = verifier(make_state(["opp_m2_planted_fee"], [opp]))
        assert "opp_m2_planted_fee" in get_rejected_ids(result)

    def test_planted_fee_reason_mentions_fee(self):
        opp = _base_opp({
            "id":               "opp_m2_planted_fee",
            "application_fee":  True,
            "planted":          True
        })
        result = verifier(make_state(["opp_m2_planted_fee"], [opp]))
        reason = next(
            r["reason"] for r in result["rejected"]
            if r["id"] == "opp_m2_planted_fee"
        )
        assert "fee" in reason.lower()


# ── Individual rejection rules ────────────────────────────────────────────────
class TestRejectionRules:

    def test_expired_deadline_rejected(self):
        opp = _base_opp({"id": "opp_exp", "deadline": "2020-01-01"})
        result = verifier(make_state(["opp_exp"], [opp]))
        assert "opp_exp" in get_rejected_ids(result)

    def test_rolling_deadline_not_rejected(self):
        opp = _base_opp({"id": "opp_rolling", "deadline": "rolling"})
        result = verifier(make_state(["opp_rolling"], [opp]))
        assert "opp_rolling" not in get_rejected_ids(result)

    def test_deadline_today_not_expired(self):
        """A deadline of today is NOT past — must not be rejected for expiry."""
        today_str = date.today().strftime("%Y-%m-%d")
        opp = _base_opp({"id": "opp_today_dl", "deadline": today_str})
        result = verifier(make_state(["opp_today_dl"], [opp]))
        # May end up in recheck (near-deadline = 0 days) but not expired-rejected
        expired_rejection = any(
            r["id"] == "opp_today_dl" and "passed" in r["reason"].lower()
            for r in result["rejected"]
        )
        assert not expired_rejection, "Deadline of today should NOT be treated as expired"

    def test_unparseable_deadline_treated_as_expired(self):
        """A deadline string that cannot be parsed is treated as expired and rejected."""
        opp = _base_opp({"id": "opp_bad_date", "deadline": "not-a-date"})
        result = verifier(make_state(["opp_bad_date"], [opp]))
        assert "opp_bad_date" in get_rejected_ids(result)

    def test_application_fee_rejected(self):
        opp = _base_opp({"id": "opp_fee", "application_fee": True})
        result = verifier(make_state(["opp_fee"], [opp]))
        assert "opp_fee" in get_rejected_ids(result)

    def test_missing_source_url_rejected(self):
        opp = _base_opp({"id": "opp_no_url", "source_url": ""})
        result = verifier(make_state(["opp_no_url"], [opp]))
        assert "opp_no_url" in get_rejected_ids(result)

    def test_unofficial_url_rejected_when_online(self):
        opp = _base_opp({
            "id":         "opp_bitly",
            "source_url": "https://bit.ly/abc123"
        })
        result = verifier(make_state(["opp_bitly"], [opp], offline=False))
        assert "opp_bitly" in get_rejected_ids(result)

    def test_unofficial_url_allowed_when_offline(self):
        """URL check must be skipped entirely when offline=True."""
        opp = _base_opp({
            "id":         "opp_bitly_offline",
            "source_url": "https://bit.ly/abc123"
        })
        result = verifier(make_state(["opp_bitly_offline"], [opp], offline=True))
        assert "opp_bitly_offline" not in get_rejected_ids(result)

    @pytest.mark.parametrize("url_pattern,opp_id", [
        ("https://bit.ly/abc",                       "opp_url_bitly"),
        ("https://tinyurl.com/abc",                  "opp_url_tinyurl"),
        ("https://t.co/abc",                         "opp_url_tco"),
        ("https://forms.gle/abc",                    "opp_url_formsgle"),
        ("https://docs.google.com/forms/abc",        "opp_url_googleforms"),
        ("https://linktr.ee/someorg",                "opp_url_linktree"),
    ])
    def test_all_unofficial_url_patterns_rejected(self, url_pattern, opp_id):
        """Every known unofficial URL pattern must trigger rejection when online."""
        opp = _base_opp({"id": opp_id, "source_url": url_pattern})
        result = verifier(make_state([opp_id], [opp], offline=False))
        assert opp_id in get_rejected_ids(result), (
            f"URL pattern '{url_pattern}' should trigger rejection but did not"
        )

    def test_missing_required_field_rejected(self):
        opp = _base_opp({"id": "opp_no_title"})
        del opp["title"]
        result = verifier(make_state(["opp_no_title"], [opp]))
        assert "opp_no_title" in get_rejected_ids(result)

    def test_scam_signal_in_title_rejected(self):
        opp = _base_opp({
            "id":    "opp_scam",
            "title": "Guaranteed Selection Internship Program"
        })
        result = verifier(make_state(["opp_scam"], [opp]))
        assert "opp_scam" in get_rejected_ids(result)

    def test_scam_signal_in_org_rejected(self):
        opp = _base_opp({
            "id":  "opp_scam_org",
            "org": "100% Scholarship Foundation"
        })
        result = verifier(make_state(["opp_scam_org"], [opp]))
        assert "opp_scam_org" in get_rejected_ids(result)

    def test_guaranteed_admission_scam_phrase_rejected(self):
        """'guaranteed admission' scam phrase must be detected."""
        opp = _base_opp({
            "id":    "opp_scam_admission",
            "title": "Guaranteed Admission MBA Program"
        })
        result = verifier(make_state(["opp_scam_admission"], [opp]))
        assert "opp_scam_admission" in get_rejected_ids(result)

    def test_guaranteed_job_scam_phrase_rejected(self):
        """'guaranteed job' scam phrase must be detected."""
        opp = _base_opp({
            "id":    "opp_scam_job",
            "title": "Guaranteed Job Placement Bootcamp"
        })
        result = verifier(make_state(["opp_scam_job"], [opp]))
        assert "opp_scam_job" in get_rejected_ids(result)


# ── Clean listing passes ──────────────────────────────────────────────────────
class TestCleanListing:

    def test_clean_listing_is_verified(self):
        opp = _base_opp()
        result = verifier(make_state(["opp_test_base"], [opp]))
        assert "opp_test_base" in result["verified"]

    def test_clean_listing_not_in_rejected(self):
        opp = _base_opp()
        result = verifier(make_state(["opp_test_base"], [opp]))
        assert "opp_test_base" not in get_rejected_ids(result)

    def test_clean_listing_not_in_recheck(self):
        opp = _base_opp()
        result = verifier(make_state(["opp_test_base"], [opp]))
        assert "opp_test_base" not in result["recheck"]


# ── Recheck (doubtful) logic ──────────────────────────────────────────────────
class TestRecheckRound:

    def test_recheck_fires_max_once(self):
        """
        Round 0: a stale listing (last_checked > 30 days) should be sent to
        Scout for re-check (LLM unavailable → fallback is 'recheck').
        Round 1: same listing confirmed by Scout must NOT go to recheck again.
        """
        old_date = (date.today() - timedelta(days=45)).strftime("%Y-%m-%d")
        opp = _base_opp({
            "id":           "opp_recheck_once",
            "last_checked": old_date
        })

        # Round 0 — Verifier sends it to Scout
        state_r0 = make_state(
            candidates=["opp_recheck_once"],
            opportunities=[opp],
            round_v=0
        )
        result_r0 = verifier(state_r0)
        # LLM unavailable → falls back to 'recheck'; listing must be in recheck
        assert "opp_recheck_once" in result_r0["recheck"], (
            "Stale listing (last_checked > 30 days) should be sent to recheck in round 0"
        )

        # Round 1 — Scout re-confirmed, Verifier must NOT recheck again
        state_r1 = make_state(
            candidates=[],
            opportunities=[opp],
            round_v=1,
            recheck_responses=["opp_recheck_once"]
        )
        result_r1 = verifier(state_r1)
        assert "opp_recheck_once" not in result_r1["recheck"],             "Verifier sent the same ID to recheck a second time — must only fire once"

    def test_round1_processes_recheck_responses_not_candidates(self):
        """In round 1, candidates list is ignored — only recheck_responses matter."""
        opp_a = _base_opp({"id": "opp_a"})
        opp_b = _base_opp({"id": "opp_b"})

        state = make_state(
            candidates=["opp_a"],            # should be ignored in round 1
            opportunities=[opp_a, opp_b],
            round_v=1,
            recheck_responses=["opp_b"]      # only this should be processed
        )
        result = verifier(state)

        assert "opp_b" in result["verified"]
        assert "opp_a" not in result["verified"]
        assert "opp_a" not in get_rejected_ids(result)

    def test_near_deadline_listing_goes_to_recheck(self):
        """A listing whose deadline is 2 days away triggers doubtful → recheck in round 0."""
        near_deadline = (date.today() + timedelta(days=2)).strftime("%Y-%m-%d")
        opp = _base_opp({
            "id":       "opp_near_dl",
            "deadline": near_deadline,
        })
        state = make_state(candidates=["opp_near_dl"], opportunities=[opp], round_v=0)
        result = verifier(state)
        # LLM unavailable → falls back to 'recheck'; must NOT be hard-rejected
        assert "opp_near_dl" not in get_rejected_ids(result), (
            "Near-deadline listing should not be hard-rejected"
        )
        assert "opp_near_dl" in result["recheck"], (
            "Near-deadline listing (deadline in 2 days) should be flagged as doubtful → recheck"
        )


# ── Edge cases ────────────────────────────────────────────────────────────────
class TestEdgeCases:

    def test_unknown_id_does_not_crash(self):
        result = verifier(make_state(["opp_ghost"], []))
        assert "opp_ghost" in get_rejected_ids(result)

    def test_empty_candidates_does_not_crash(self):
        result = verifier(make_state([], []))
        assert result is not None

    def test_messages_always_returned(self):
        result = verifier(make_state([], []))
        assert "messages" in result
        assert isinstance(result["messages"], list)
        assert len(result["messages"]) > 0

    def test_returns_only_owned_keys(self):
        """Verifier must not write keys it does not own."""
        opp = _base_opp()
        result = verifier(make_state(["opp_test_base"], [opp]))
        owned = {"verified", "rejected", "recheck", "messages"}
        for key in result:
            assert key in owned,                 f"Verifier returned unexpected state key: '{key}'"

    def test_no_verified_listing_has_expired_deadline(self):
        expired = _base_opp({"id": "opp_exp2",   "deadline": "2020-06-01"})
        clean   = _base_opp({"id": "opp_clean2"})
        result  = verifier(make_state(
            ["opp_exp2", "opp_clean2"], [expired, clean]
        ))
        assert "opp_exp2"   not in result["verified"]
        assert "opp_clean2" in     result["verified"]

    def test_no_verified_listing_has_fee(self):
        fee   = _base_opp({"id": "opp_fee2",   "application_fee": True})
        clean = _base_opp({"id": "opp_clean3"})
        result = verifier(make_state(
            ["opp_fee2", "opp_clean3"], [fee, clean]
        ))
        assert "opp_fee2"   not in result["verified"]
        assert "opp_clean3" in     result["verified"]

    def test_existing_messages_are_preserved(self):
        """Messages from earlier agents must not be wiped."""
        opp = _base_opp()
        prior_msg = {
            "sender": "Scout", "recipient": "all",
            "type": "info", "text": "Scout found 1 candidate"
        }
        state = make_state(["opp_test_base"], [opp])
        state["messages"] = [prior_msg]
        result = verifier(state)
        assert prior_msg in result["messages"]
