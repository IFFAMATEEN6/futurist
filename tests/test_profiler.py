import glob
from agents.profiler import run

KEYS = ["year", "gpa", "field", "nationality", "skills", "interests",
        "strength_score", "strength_notes"]

def test_all_samples():
    files = glob.glob("data/sample_students/*.txt")
    assert len(files) >= 3
    for f in files:
        out = run({"student_input": open(f, encoding="utf-8").read()})
        assert set(out) <= {"profile", "messages"}
        for k in KEYS:
            assert k in out["profile"]
        assert 0 <= out["profile"]["strength_score"] <= 100

def test_bad_input_no_crash():
    for bad in ["", "   ", "@@@###", None]:
        out = run({"student_input": bad})
        assert "messages" in out

def test_ml_alias():
    out = run({"student_input": "Third-year Computer Science. Skills: ML, Python"})
    assert "Machine Learning" in out["profile"]["skills"]

def test_missing_gpa_is_none():
    out = run({"student_input": "Second-year Computer Science. Skills: Python"})
    assert out["profile"]["gpa"] is None
    assert any("gpa" in m["text"].lower() for m in out["messages"])