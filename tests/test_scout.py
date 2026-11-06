"""Scout tests (M1). The dataset is faked, so these need no real data file."""
import json
import os

import config
from agents import scout
from scripts.validate_data import validate_records


def rec(i, type_, title, deadline="2026-12-20", skills=None):
    return {"id": f"opp_{i:03d}", "title": title, "org": "Org", "type": type_, "deadline": deadline,
            "eligibility": {}, "required_skills": skills or [], "effort_hours": 5,
            "application_fee": False, "source_url": f"https://x.org/{i}", "last_checked": "2026-11-05",
            "description": ""}


DATA = [
    rec(1, "internship", "AI Research Intern", skills=["machine learning"]),
    rec(2, "internship", "Accounting Intern"),
    rec(3, "scholarship", "General Merit Scholarship"),
    rec(4, "hackathon", "Weekend Hackathon"),
    rec(5, "internship", "Expired AI Intern", deadline="2020-01-01"),
]


def patch(monkeypatch, data=DATA):
    monkeypatch.setattr(scout, "load_index", lambda: scout.build_index(data))


# ---------- interests ----------
def test_extract_interests_uses_interests_part_not_skills():
    text = "Skills: Python, HTML, SQL. Interests: AI internships and scholarships"
    got = scout.extract_interests(text)
    assert set(got["types"]) == {"internship", "scholarship"}
    assert got["topics"] == ["ai"]                    # HTML / SQL in skills are ignored


def test_whole_word_matching_only():
    assert scout.extract_interests("Interests: maintain train")["topics"] == []   # not 'ai'


def test_punctuation_does_not_hide_keywords():
    assert "ai" in scout.extract_interests("Interests: AI-powered tools")["topics"]


# ---------- selection ----------
def test_filters_by_type_and_topic_best_first(monkeypatch):
    patch(monkeypatch)
    out = scout.run({"student_input": "Interests: AI internships and scholarships"})
    ids = [c["id"] for c in out["candidates"]]
    assert ids[0] == "opp_001"                        # internship + AI + not expired
    assert "opp_004" not in ids                       # hackathon not requested
    assert out["messages"][0]["recipient"] == "verifier"


def test_expired_listings_are_kept_for_the_verifier(monkeypatch):
    patch(monkeypatch)
    out = scout.run({"student_input": "Interests: AI internships"})
    assert "opp_005" in [c["id"] for c in out["candidates"]]


def test_no_interests_gives_default_candidates(monkeypatch):
    patch(monkeypatch)
    out = scout.run({"student_input": "hello"})
    assert len(out["candidates"]) == len(DATA)
    assert out["candidates"][-1]["id"] == "opp_005"   # expired ones go last


def test_interests_with_no_match_gives_clear_message(monkeypatch):
    patch(monkeypatch)
    out = scout.run({"student_input": "Interests: cybersecurity workshops"})
    assert out["candidates"] == []
    assert "No opportunities match" in out["messages"][0]["text"]


def test_interests_override_from_form(monkeypatch):
    patch(monkeypatch)
    out = scout.run({"student_input": "", "interests_override": ["hackathons"]})
    assert [c["id"] for c in out["candidates"]] == ["opp_004"]


def test_candidate_cap(monkeypatch):
    patch(monkeypatch, [rec(i, "internship", "AI Intern") for i in range(50)])
    out = scout.run({"student_input": "Interests: AI internships"})
    assert len(out["candidates"]) == config.MAX_CANDIDATES


def test_output_records_are_copies(monkeypatch):
    patch(monkeypatch)
    out = scout.run({"student_input": "Interests: AI internships"})
    out["candidates"][0]["title"] = "CHANGED"
    assert DATA[0]["title"] == "AI Research Intern"


# ---------- re-check mode ----------
def test_recheck_mode_replies_and_keeps_other_candidates(monkeypatch):
    patch(monkeypatch)
    state = {"student_input": "", "candidates": [DATA[0], DATA[2]], "recheck": ["opp_001"]}
    out = scout.run(state)
    assert len(out["candidates"]) == 2
    assert out["messages"][0]["type"] == "response"
    assert "opp_001" in out["messages"][0]["text"]


def test_recheck_unknown_id_does_not_crash(monkeypatch):
    patch(monkeypatch)
    out = scout.run({"candidates": [], "recheck": ["opp_999"]})
    assert "Could not find" in out["messages"][0]["text"]


# ---------- errors ----------
def test_broken_dataset_gives_error_message_not_crash(monkeypatch):
    def broken():
        raise FileNotFoundError("nope")
    monkeypatch.setattr(scout, "load_index", broken)
    out = scout.run({"student_input": "Interests: AI"})
    assert out["candidates"] == [] and out["messages"][0]["type"] == "error"


# ---------- dataset cache ----------
def test_dataset_is_cached_until_the_file_changes(monkeypatch, tmp_path):
    path = tmp_path / "opportunities.json"
    path.write_text(json.dumps(DATA[:2]), encoding="utf-8")
    monkeypatch.setattr(config, "OPPORTUNITIES_PATH", path)
    first = scout.load_index()
    assert scout.load_index() is first                # same object: no re-read
    path.write_text(json.dumps(DATA), encoding="utf-8")
    os.utime(path, (path.stat().st_atime + 10, path.stat().st_mtime + 10))
    assert len(scout.load_index()) == len(DATA)       # file changed: re-read


# ---------- dataset checker (scripts/validate_data.py) ----------
def test_validator_accepts_a_good_record():
    errors, _ = validate_records([rec(1, "internship", "A")])
    assert errors == []


def test_validator_catches_duplicate_id_bad_type_and_bad_date():
    bad = [rec(1, "internship", "A"), rec(1, "party", "B", deadline="soon")]
    text = " ".join(validate_records(bad)[0])
    assert "duplicate id" in text and "type must be" in text and "deadline must be" in text


def test_validator_flags_placeholder_records():
    placeholder = {**rec(2, "internship", "[PLACEHOLDER] A"), "source_url": "https://example.com/x"}
    assert any("placeholder" in w for w in validate_records([placeholder])[1])
