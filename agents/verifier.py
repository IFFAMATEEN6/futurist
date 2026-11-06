"""Deterministic listing checks with honest evidence and per-record isolation."""
import copy
from datetime import date
from urllib.parse import urlsplit

import config
from domain import canonical_url, record_errors, safe_url, today
from state import make_msg

BLOCKED_HOSTS = ("bit.ly", "tinyurl.com", "t.co", "forms.gle", "linktr.ee")
SCAM_PHRASES = ("guaranteed selection", "guaranteed admission", "100% scholarship", "guaranteed job")


def _url_looks_unofficial(url):
    if not safe_url(url):
        return True
    parsed = urlsplit(url)
    host = parsed.hostname.lower().rstrip(".")
    return (any(host == value or host.endswith("." + value) for value in BLOCKED_HOSTS)
            or (host == "docs.google.com" and parsed.path.lower().startswith("/forms")))


def _doubtful_reasons(opp):
    reasons = []
    checked = date.fromisoformat(opp["last_checked"])
    age = (today() - checked).days
    if age > 30:
        reasons.append(f"Catalog source check is {age} days old; a fresh source review is needed.")
    if age < 0:
        reasons.append("Catalog check date is in the future; its provenance needs review.")
    if opp["deadline"] != "rolling":
        days = (date.fromisoformat(opp["deadline"]) - today()).days
        if 0 <= days <= 3:
            reasons.append(f"Deadline is in {days} day(s); confirm the exact closing time on the source.")
    return reasons


def run(state):
    verified, rejected, recheck, messages = [], [], [], []
    seen_ids, seen_sources = set(), set()
    round_v = state.get("round_v", 0)
    messages.append(make_msg("verifier", "all", "info",
                             f"Checking catalog evidence for {len(state.get('candidates', []))} candidates, pass {round_v + 1}."))
    for index, raw in enumerate(state.get("candidates") or []):
        errors = record_errors(raw)
        opp = copy.deepcopy(raw) if isinstance(raw, dict) else {"id": f"invalid_{index}", "title": "Invalid catalog record"}
        reason = "; ".join(errors)
        if not reason:
            combined = " ".join(str(opp.get(key, "")) for key in ("title", "org", "description")).lower()
            source = canonical_url(opp["source_url"])
            if opp["id"] in seen_ids or source in seen_sources:
                reason = "Duplicate catalog identity or source; excluded from recommendations."
            elif opp["deadline"] != "rolling" and date.fromisoformat(opp["deadline"]) < today():
                reason = "Deadline has passed."
            elif opp["application_fee"]:
                reason = "Charges an application fee."
            elif _url_looks_unofficial(opp["source_url"]):
                reason = "Source is a shortened URL or indirect form; use the official listing."
            elif any(phrase in combined for phrase in SCAM_PHRASES):
                reason = "Scam signal: guaranteed-selection, admission, scholarship or job claim."
            seen_ids.add(opp["id"])
            seen_sources.add(source)
        if reason:
            rejected.append((opp, reason))
            messages.append(make_msg("verifier", "all", "reject", f"{opp.get('title', 'Listing')}: {reason}"))
            continue
        doubts = _doubtful_reasons(opp)
        if doubts and round_v < config.MAX_VERIFIER_ROUNDS:
            recheck.append(opp["id"])
            messages.append(make_msg("verifier", "scout", "challenge",
                                     f"Re-read {opp['id']} ({opp['title']}). " + " ".join(doubts)))
            continue
        warnings = list(opp.get("catalog_warnings") or []) + doubts
        if doubts:
            evidence = state.get("recheck_evidence", {}).get(opp["id"], {})
            warnings.append(evidence.get("note", "No new source evidence was supplied; review is still required."))
        opp["verification_status"] = "needs_review" if doubts else "catalog_checked"
        opp["verification_warnings"] = list(dict.fromkeys(warnings))
        opp["source_checked_live"] = False
        verified.append(opp)
    messages.append(make_msg("verifier", "matcher", "result",
                             f"Catalog checks complete: {len(verified)} retained, {len(rejected)} rejected, "
                             f"{len(recheck)} awaiting Scout. Source pages were not checked live; retain review notes."))
    return {"verified": verified, "rejected": rejected, "recheck": recheck, "messages": messages}
