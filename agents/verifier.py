"""Verifier agent. Owner: M2.

Contract (defined in state.py / graph.py):
  Entry point : run(state) -> dict
  Reads       : candidates (list[dict] full records), round_v (int),
                recheck (list[str] ids, populated on recheck round),
                offline (bool)
  Writes      : verified (list[dict] full records),
                rejected (list[tuple[dict, str]]  i.e. (opp_record, reason)),
                recheck  (list[str] ids to re-check),
                messages (list[Msg] — appended via make_msg(), never replaced)
"""

from datetime import date, datetime

# ── Import guards ─────────────────────────────────────────────────────────────
# config.py lives on Iffa's branch; fall back to sensible defaults.
try:
    import config
    _today_str = config.TODAY          # always a string "YYYY-MM-DD"
    TODAY = date.fromisoformat(_today_str)
except (ImportError, AttributeError, ValueError):
    TODAY = date.today()

# state.py lives on Iffa's branch; fall back to a local make_msg.
try:
    from state import make_msg
except ImportError:
    from datetime import datetime as _dt
    def make_msg(sender, recipient, type, text):        # noqa: A002
        return {"sender": sender, "recipient": recipient,
                "type": type, "text": text,
                "ts": _dt.now().isoformat(timespec="seconds")}

# llm.py lives on yusra-shahid; fall back gracefully.
try:
    from llm import ask
except ImportError:
    def ask(prompt, system="", want_json=False):
        return None, "llm.py not available"
# ─────────────────────────────────────────────────────────────────────────────


# ── Constants ─────────────────────────────────────────────────────────────────
REQUIRED_FIELDS = [
    "id", "title", "org", "type",
    "deadline", "eligibility", "source_url", "last_checked",
]

REJECT_REASONS = {
    "expired":    "Deadline has passed",
    "fee":        "Charges an application fee",
    "no_url":     "Missing source URL",
    "bad_url":    "URL does not look official (shortened or redirect link)",
    "scam":       "Scam signal detected in title or org name",
    "incomplete": "Required field is missing",
}

SCAM_PHRASES = [
    "guaranteed selection",
    "guaranteed admission",
    "100% scholarship",
    "guaranteed job",
]

UNOFFICIAL_URL_PATTERNS = [
    "bit.ly",
    "tinyurl.com",
    "t.co",
    "forms.gle",
    "docs.google.com/forms",
    "linktr.ee",
]
# ─────────────────────────────────────────────────────────────────────────────


# ── Rule helpers ──────────────────────────────────────────────────────────────
def _missing_fields(opp):
    return [f for f in REQUIRED_FIELDS if not opp.get(f)]


def _is_expired(deadline_str):
    if deadline_str == "rolling":
        return False
    try:
        return datetime.strptime(deadline_str, "%Y-%m-%d").date() < TODAY
    except ValueError:
        return True   # unparseable date -> treat as expired


def _has_fee(opp):
    return opp.get("application_fee") is True


def _has_scam_signal(opp):
    combined = (opp.get("title", "") + " " + opp.get("org", "")).lower()
    return any(phrase in combined for phrase in SCAM_PHRASES)


def _url_looks_unofficial(url):
    return any(pattern in url for pattern in UNOFFICIAL_URL_PATTERNS)


def _doubtful_reasons(opp):
    """
    Returns list of doubt reasons.
    Empty list  -> not doubtful.
    Non-empty   -> send back to Scout for re-check.
    """
    reasons = []

    # last_checked older than 30 days
    try:
        last_checked = datetime.strptime(opp["last_checked"], "%Y-%m-%d").date()
        age = (TODAY - last_checked).days
        if age > 30:
            reasons.append(f"last_checked is {age} days old (limit: 30)")
    except (ValueError, KeyError):
        reasons.append("last_checked is missing or malformed")

    # deadline within 3 days
    deadline_str = opp.get("deadline", "rolling")
    if deadline_str != "rolling":
        try:
            deadline = datetime.strptime(deadline_str, "%Y-%m-%d").date()
            days_left = (deadline - TODAY).days
            if 0 <= days_left <= 3:
                reasons.append(f"deadline is in {days_left} day(s) — very soon")
        except ValueError:
            pass   # already caught by _is_expired

    return reasons
# ─────────────────────────────────────────────────────────────────────────────


# ── LLM review ────────────────────────────────────────────────────────────────
def _llm_review(opp, doubt_reasons):
    """
    Ask the LLM whether a doubtful listing is legitimate.
    Returns: "approve" | "reject" | "recheck"
    Falls back to "recheck" when LLM unavailable or result is None.
    """
    prompt = (
        "You are a scholarship and internship fraud detector.\n"
        "Review this opportunity listing and reply with EXACTLY one word:\n"
        "approve, reject, or recheck.\n\n"
        f"Title:            {opp.get('title')}\n"
        f"Organization:     {opp.get('org')}\n"
        f"Type:             {opp.get('type')}\n"
        f"Deadline:         {opp.get('deadline')}\n"
        f"Source URL:       {opp.get('source_url')}\n"
        f"Application fee:  {opp.get('application_fee')}\n"
        f"Concerns raised:  {'; '.join(doubt_reasons)}\n\n"
        "approve = listing looks legitimate\n"
        "reject  = looks fake, scam, or unreliable\n"
        "recheck = cannot decide; Scout should verify the source\n"
    )

    result, _note = ask(prompt)   # unpack tuple — ask() never raises

    if result is None:
        # All providers failed; safe default: send back to Scout
        return "recheck"

    answer = result.strip().lower()
    return answer if answer in ("approve", "reject", "recheck") else "recheck"
# ─────────────────────────────────────────────────────────────────────────────


# ── Main agent function ───────────────────────────────────────────────────────
def run(state):
    """
    Verifier agent — called by graph.py as: run(state)

    Reads from state:
        candidates      list[dict]  — full opportunity records from Scout
        round_v         int         — 0 = first pass, >0 = recheck pass
        recheck         list[str]   — ids Verifier asked Scout to re-check
                                      (non-empty on the recheck round)
        offline         bool        — True = skip URL pattern check

    Returns (owns these keys only):
        verified        list[dict]        — full records that passed all checks
        rejected        list[tuple]       — [(opp_record, reason_str), ...]
        recheck         list[str]         — ids sent back to Scout
        messages        list[Msg]         — appended, never replaced
    """
    new_messages = []
    verified     = []
    rejected     = []
    recheck_out  = []

    round_v = state.get("round_v", 0)
    offline = state.get("offline", False)

    # Candidates is always a list of full dicts from Scout.
    # On a recheck round, Scout has updated the records in-place;
    # we only re-verify the ids that were originally flagged.
    all_candidates = state.get("candidates", [])
    opp_map = {o["id"]: o for o in all_candidates if isinstance(o, dict)}

    # In both round 0 and round 1, evaluate all candidates.
    # In round 1 (round_v > 0), doubtful check is skipped so confirmed
    # listings pass directly to verified without re-triggering Loop 1.
    ids_to_check = list(opp_map.keys())

    new_messages.append(make_msg(
        "verifier", "all", "info",
        f"Starting verification — round {round_v + 1}, "
        f"{len(ids_to_check)} listing(s) to check."
    ))

    # ── Check each listing ────────────────────────────────────────────────────
    for opp_id in ids_to_check:
        opp = opp_map.get(opp_id)

        if not opp:
            rejected.append(({"id": opp_id}, "ID not found in candidates"))
            new_messages.append(make_msg(
                "verifier", "scout", "reject",
                f"[{opp_id}] Not found in candidates — rejected."
            ))
            continue

        title = opp.get("title", opp_id)

        # ── RULE 1: missing required fields ──────────────────────────────────
        missing = _missing_fields(opp)
        if missing:
            rejected.append((opp, f"{REJECT_REASONS['incomplete']}: {missing}"))
            new_messages.append(make_msg(
                "verifier", "all", "reject",
                f"[{title}] Rejected — missing fields: {missing}"
            ))
            continue

        # ── RULE 2: expired deadline ──────────────────────────────────────────
        if _is_expired(opp["deadline"]):
            rejected.append((opp, REJECT_REASONS["expired"]))
            new_messages.append(make_msg(
                "verifier", "all", "reject",
                f"[{title}] Rejected — deadline passed ({opp['deadline']})"
            ))
            continue

        # ── RULE 3: application fee ───────────────────────────────────────────
        if _has_fee(opp):
            rejected.append((opp, REJECT_REASONS["fee"]))
            new_messages.append(make_msg(
                "verifier", "all", "reject",
                f"[{title}] Rejected — charges an application fee"
            ))
            continue

        # ── RULE 4: missing URL ───────────────────────────────────────────────
        url = opp.get("source_url", "")
        if not url:
            rejected.append((opp, REJECT_REASONS["no_url"]))
            new_messages.append(make_msg(
                "verifier", "all", "reject",
                f"[{title}] Rejected — no source URL"
            ))
            continue

        # ── RULE 5: unofficial URL — skipped when offline ─────────────────────
        if not offline and _url_looks_unofficial(url):
            rejected.append((opp, REJECT_REASONS["bad_url"]))
            new_messages.append(make_msg(
                "verifier", "all", "reject",
                f"[{title}] Rejected — URL looks unofficial: {url}"
            ))
            continue

        # ── RULE 6: scam signals ──────────────────────────────────────────────
        if _has_scam_signal(opp):
            rejected.append((opp, REJECT_REASONS["scam"]))
            new_messages.append(make_msg(
                "verifier", "all", "reject",
                f"[{title}] Rejected — scam signal in title or org"
            ))
            continue

        # ── DOUBTFUL CHECK — only in round 0, fires max once ─────────────────
        if round_v == 0:
            doubt = _doubtful_reasons(opp)
            if doubt:
                llm_verdict = _llm_review(opp, doubt)

                if llm_verdict == "reject":
                    rejected.append((
                        opp,
                        f"LLM flagged as suspicious. Doubts: {'; '.join(doubt)}"
                    ))
                    new_messages.append(make_msg(
                        "verifier", "all", "reject",
                        f"[{title}] Rejected after LLM review — {'; '.join(doubt)}"
                    ))

                elif llm_verdict == "approve":
                    verified.append(opp)
                    new_messages.append(make_msg(
                        "verifier", "all", "result",
                        f"[{title}] Verified (LLM approved despite: {'; '.join(doubt)})"
                    ))

                else:   # "recheck" — challenge Scout
                    recheck_out.append(opp_id)
                    new_messages.append(make_msg(
                        "verifier", "scout", "challenge",
                        f"[{title}] Doubtful — please re-check source. "
                        f"Reasons: {'; '.join(doubt)}"
                    ))

                continue   # do not fall through to verified

        # ── PASSED ALL CHECKS ─────────────────────────────────────────────────
        verified.append(opp)
        new_messages.append(make_msg(
            "verifier", "all", "result",
            f"[{title}] Verified"
        ))

    # ── Summary ───────────────────────────────────────────────────────────────
    new_messages.append(make_msg(
        "verifier", "all", "info",
        f"Round {round_v + 1} complete — "
        f"{len(verified)} verified, "
        f"{len(rejected)} rejected, "
        f"{len(recheck_out)} sent to Scout for re-check."
    ))

    return {
        "verified": verified,
        "rejected": rejected,
        "recheck":  recheck_out,
        "messages": new_messages,
    }
