"""Shared validation and normalization for catalog records and student evidence."""
import math
import re
from datetime import date
from urllib.parse import urlsplit, urlunsplit

import config

TYPES = ("internship", "scholarship", "hackathon", "competition", "workshop")
SKILL_ALIASES = {"ml": "machine learning", "dl": "deep learning", "py": "python",
                 "js": "javascript", "dsa": "data structures", "ds": "data structures",
                 "ui/ux": "ui/ux design", "ux": "ui/ux design", "aws": "cloud",
                 "gcp": "cloud", "azure": "cloud"}


def today():
    return date.fromisoformat(config.TODAY)


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (ValueError, TypeError):
        return None


def valid_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def safe_url(value):
    if not isinstance(value, str) or any(c.isspace() for c in value):
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme in ("https", "http") and bool(parsed.hostname)
                and not parsed.username and not parsed.password and parsed.port in (None, 80, 443))
    except ValueError:
        return False


def canonical_url(value):
    if not safe_url(value):
        return str(value)
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", ""))


def normalize_skill(value):
    value = re.sub(r"\([^)]*\)", "", str(value)).strip().lower()
    value = re.sub(r"^(?:basic|beginner|intermediate|advanced|proficient in)\s+", "", value)
    value = re.sub(r"\s+", " ", value)
    return SKILL_ALIASES.get(value, value)


def normalize_field(value):
    value = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return {"cs": "computer science", "bscs": "computer science", "bs cs": "computer science",
            "se": "software engineering", "ds": "data science", "hr": "human resources"}.get(value, value)


def normalize_nationality(value):
    value = str(value or "").strip().lower()
    return {"pakistan": "pakistani", "india": "indian", "usa": "american", "us": "american",
            "united states": "american", "uk": "british", "united kingdom": "british",
            "nigeria": "nigerian", "bangladesh": "bangladeshi", "canada": "canadian"}.get(value, value)


def record_errors(record):
    """Validate one record before inspecting its values; never assume input types."""
    if not isinstance(record, dict):
        return ["listing must be an object"]
    errors = []
    for field in ("id", "title", "org"):
        if not isinstance(record.get(field), str) or not record[field].strip():
            errors.append(f"missing or invalid {field}")
    if record.get("type") not in TYPES:
        errors.append("type must be one of " + ", ".join(TYPES))
    if record.get("deadline") != "rolling" and not valid_date(record.get("deadline")):
        errors.append("deadline must be YYYY-MM-DD or rolling")
    if not valid_date(record.get("last_checked")):
        errors.append("last_checked must be YYYY-MM-DD")
    if not safe_url(record.get("source_url")):
        errors.append("source_url must be an HTTP(S) URL without credentials")
    if not isinstance(record.get("application_fee"), bool):
        errors.append("application_fee must be a boolean")
    if not isinstance(record.get("required_skills"), list) or any(
            not isinstance(s, str) or not s.strip() for s in record.get("required_skills", [])):
        errors.append("required_skills must be a list of nonempty strings")
    effort = number(record.get("effort_hours"))
    if effort is None or not isinstance(record.get("effort_hours"), (int, float)) or not 0 <= effort <= 1000:
        errors.append("effort_hours must be a number between 0 and 1000")
    rules = record.get("eligibility")
    if not isinstance(rules, dict):
        errors.append("eligibility must be an object")
    else:
        for key, low, high in (("min_year", 1, 10), ("max_year", 1, 10), ("min_gpa", 0, 4)):
            value = rules.get(key)
            if value is not None:
                parsed = number(value)
                if (not isinstance(value, (int, float)) or parsed is None or not low <= parsed <= high
                        or ("year" in key and not parsed.is_integer())):
                    errors.append(f"eligibility.{key} must be a number in {low}..{high}")
        for key in ("fields", "nationalities"):
            values = rules.get(key, [])
            if not isinstance(values, list) or any(not isinstance(s, str) for s in values):
                errors.append(f"eligibility.{key} must be a list of strings")
        if (number(rules.get("min_year")) is not None and number(rules.get("max_year")) is not None
                and rules["min_year"] > rules["max_year"]):
            errors.append("eligibility.min_year exceeds max_year")
    if "description" in record and not isinstance(record["description"], str):
        errors.append("description must be text")
    if "eligibility_complete" in record and not isinstance(record["eligibility_complete"], bool):
        errors.append("eligibility_complete must be a boolean")
    return errors
