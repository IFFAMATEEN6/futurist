# conftest.py
# Adds the project root to sys.path so pytest can find agents/, llm.py, etc.
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
