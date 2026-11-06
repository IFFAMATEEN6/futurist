# conftest.py
# Adds the project root to sys.path so pytest can find agents/, llm.py, etc.
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import pytest


@pytest.fixture(autouse=True)
def deterministic_local_execution(monkeypatch):
    import config
    import llm
    monkeypatch.setattr(config, "TODAY", "2026-11-07")
    monkeypatch.setattr(llm, "PROVIDERS", [])
