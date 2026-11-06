"""Validate catalog structure without claiming live source verification."""
import json

import config
from domain import canonical_url, record_errors


def validate_records(records):
    if not isinstance(records, list):
        return ["dataset must be a list of records"], []
    errors, warnings, ids, sources = [], [], set(), set()
    for i, record in enumerate(records, 1):
        label = f"record {i}"
        errors.extend(f"{label}: {message}" for message in record_errors(record))
        if not isinstance(record, dict):
            continue
        oid = record.get("id")
        if isinstance(oid, str):
            if oid in ids:
                errors.append(f"duplicate id: {oid}")
            ids.add(oid)
        url = record.get("source_url")
        source = canonical_url(url)
        if source in sources:
            warnings.append(f"{label}: duplicate source URL; Scout will deduplicate it")
        sources.add(source)
        text = f"{record.get('title', '')} {record.get('description', '')} {url}".lower()
        if "placeholder" in text or "example.com" in text:
            warnings.append(f"{label}: placeholder record or source")
        if record.get("eligibility_complete") is False:
            warnings.append(f"{label}: full eligibility needs source confirmation")
    return errors, warnings


def main():
    try:
        records = json.loads(config.OPPORTUNITIES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Could not read catalog: {exc}")
        return 1
    errors, warnings = validate_records(records)
    for item in errors:
        print(f"ERROR: {item}")
    for item in warnings:
        print(f"WARNING: {item}")
    print(f"Checked {len(records) if isinstance(records, list) else 0} records: {len(errors)} error(s), {len(warnings)} warning(s).")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
