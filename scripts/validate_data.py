"""Validate opportunity records before using them in the app."""
import json
import re
import sys
from datetime import date
from urllib.parse import urlparse

import config
from state import OPPORTUNITY_TYPES

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _valid_date(value: object) -> bool:
    if not isinstance(value, str) or not _DATE_PATTERN.fullmatch(value):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def validate_records(records: list) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for a list of opportunity records."""
    errors = []
    warnings = []
    seen_ids = set()

    if not isinstance(records, list):
        return ["dataset must be a list of records"], warnings

    for index, record in enumerate(records, start=1):
        label = f"record {index}"
        if not isinstance(record, dict):
            errors.append(f"{label} must be an object")
            continue

        record_id = record.get("id")
        if not isinstance(record_id, str) or not record_id.strip():
            errors.append(f"{label} is missing id")
        elif record_id in seen_ids:
            errors.append(f"duplicate id: {record_id}")
        else:
            seen_ids.add(record_id)
        label = f"{label} ({record_id})" if record_id else label

        for field in ("title", "org", "type", "deadline", "source_url", "last_checked"):
            if not record.get(field):
                errors.append(f"{label}: missing {field}")

        if record.get("type") not in OPPORTUNITY_TYPES:
            errors.append(f"{label}: type must be one of {', '.join(OPPORTUNITY_TYPES)}")

        deadline = record.get("deadline")
        if deadline != "rolling" and not _valid_date(deadline):
            errors.append(f"{label}: deadline must be YYYY-MM-DD or rolling")

        if not _valid_date(record.get("last_checked")):
            errors.append(f"{label}: last_checked must be YYYY-MM-DD")

        source_url = record.get("source_url", "")
        parsed_url = urlparse(source_url) if isinstance(source_url, str) else None
        if not parsed_url or parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
            errors.append(f"{label}: source_url must be an HTTP(S) URL")

        text = f"{record.get('title', '')} {record.get('description', '')} {source_url}".lower()
        if "placeholder" in text or "example.com" in text:
            warnings.append(f"{label}: placeholder record or source")

    return errors, warnings


def main() -> int:
    try:
        with config.OPPORTUNITIES_PATH.open(encoding="utf-8") as file:
            records = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read opportunity dataset: {exc}", file=sys.stderr)
        return 1

    errors, warnings = validate_records(records)
    for message in errors:
        print(f"ERROR: {message}")
    for message in warnings:
        print(f"WARNING: {message}")
    print(f"Checked {len(records) if isinstance(records, list) else 0} records: "
          f"{len(errors)} error(s), {len(warnings)} warning(s).")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
