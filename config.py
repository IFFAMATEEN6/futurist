"""Project settings. Owner: M1.

"""
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


# ---------- paths ----------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OPPORTUNITIES_PATH = DATA_DIR / "opportunities.json"
SKILL_MAP_PATH = DATA_DIR / "skill_map.json"
SAMPLE_STUDENTS_DIR = DATA_DIR / "sample_students"
CACHE_DIR = BASE_DIR / "cache"

# ---------- run behaviour ----------
# "Today" for every deadline check. Set TODAY_OVERRIDE in .env to freeze it
# (tests and the final demo become reproducible).
TODAY = os.getenv("TODAY_OVERRIDE") or date.today().isoformat()
REPLAY_MODE = _env_bool("REPLAY_MODE")

MAX_VERIFIER_ROUNDS = 1   # Verifier -> Scout loop
MAX_COACH_ROUNDS = 1      # Coach -> Matcher loop
MAX_CANDIDATES = 20       # Scout output cap

# ---------- LLM: Groq (Llama) ----------
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")                 # best quality
GROQ_FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "llama-3.1-8b-instant")  # faster backup
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "")        # optional local backup, e.g. "llama3.2"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
LLM_TIMEOUT = _env_int("LLM_TIMEOUT", 30)           # seconds per call
LLM_RETRIES = _env_int("LLM_RETRIES", 2)            # extra tries per provider on 429 / network errors
LLM_TEMPERATURE = _env_float("LLM_TEMPERATURE", 0.2)
LLM_MAX_TOKENS = _env_int("LLM_MAX_TOKENS", 800)    # keep small: free tier has tokens-per-minute limits