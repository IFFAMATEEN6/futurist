"""Escaped HTML components used beside Streamlit's accessible native controls."""
from html import escape

from ui.icons import icon

AGENTS = {
    "scout": ("search", "Scout", "Finds the possibilities", "Searching the local catalog", "Waiting for your profile"),
    "profiler": ("person", "Profiler", "Understands your strengths", "Structuring your experience", "Waiting for your profile"),
    "verifier": ("shield", "Verifier", "Checks the important details", "Reviewing listing evidence", "Waiting for Scout and Profiler"),
    "matcher": ("match", "Matcher", "Connects your skills to the right fit", "Comparing skills and eligibility", "Waiting for Verifier"),
    "coach": ("calendar", "Coach", "Makes your next steps practical", "Planning around your available time", "Waiting for Matcher"),
}


def esc(value):
    return escape(str(value), quote=True)


def section(eyebrow, title, subtitle="", *, anchor=""):
    return (f'<div class="section-heading" id="{esc(anchor)}"><p class="eyebrow">{esc(eyebrow)}</p>'
            f'<h2>{esc(title)}</h2>' + (f'<p>{esc(subtitle)}</p>' if subtitle else "") + '</div>')


def notice(title, text, *, tone="sage", symbol="info"):
    return f'<div class="notice {esc(tone)}">{icon(symbol)}<div><strong>{esc(title)}</strong><p>{esc(text)}</p></div></div>'


def agent_cards(view):
    cards = []
    for name, (glyph, title, description, task, waiting) in AGENTS.items():
        event = view.get("agents", {}).get(name, {})
        phase = event.get("phase", "waiting")
        state_text = {"started": "Working", "completed": "Completed", "failed": "Needs attention"}.get(phase, "Ready")
        detail = task if phase == "started" else description if phase == "completed" else waiting
        if phase == "failed":
            detail = "See the conversation for the issue and next steps."
        elapsed = event.get("elapsed_ms")
        duration = f"{elapsed / 1000:.2f} s" if elapsed is not None else ""
        pass_text = f"Pass {event['pass']}" if event.get("pass", 1) > 1 else ""
        cards.append(f'<article class="agent-card {esc(phase)}" aria-label="{title}: {state_text}">'
                     f'<div class="agent-card-top">{icon(glyph, 27)}<span>{esc(state_text)}</span></div>'
                     f'<h3>{title}</h3><p>{esc(detail)}</p>'
                     f'<div class="agent-meta">{esc(pass_text)}<span>{esc(duration)}</span></div></article>')
    return '<div class="agent-grid">' + ''.join(cards) + '</div>'


def conversation(messages, *, agent="All agents", all_messages=False):
    filtered = [m for m in messages if (agent == "All agents" or agent.lower() in (m.get("sender"), m.get("recipient")))
                and (all_messages or (m.get("sender") in AGENTS and m.get("recipient") in AGENTS))]
    if not filtered:
        return ('<div class="conversation-empty">' + icon("chat", 32) + '<h3>The conversation starts here.</h3>'
                '<p>Your agents share findings, question uncertain details and refine the plan together. Their handoffs will appear here.</p></div>')
    cards = []
    for msg in reversed(filtered):
        sender, recipient = str(msg.get("sender", "system")), str(msg.get("recipient", "all"))
        destination = "Team" if recipient == "all" else recipient.capitalize()
        timestamp = str(msg.get("ts", ""))[11:19]
        kind = str(msg.get("type", "info"))
        cards.append(f'<article class="message-card {esc(kind)}"><div class="message-route">'
                     f'<strong>{esc(sender.capitalize())}</strong>{icon("arrow", 18)}<strong>{esc(destination)}</strong>'
                     f'<time>{esc(timestamp)}</time></div><p>{esc(msg.get("text", ""))}</p></article>')
    return '<div class="message-feed">' + ''.join(cards) + '</div>'


def opportunity_card(opp, match, rank=None):
    status = match.get("eligibility_status", "conditional")
    label = {"eligible": "Meets recorded rules", "conditional": "Confirm eligibility", "ineligible": "Outside recorded requirements"}[status]
    title = opp.get("title", "Opportunity")
    rank_text = f'<span class="rank-number">{rank:02d}</span>' if rank else icon("briefcase", 26)
    deadline = "Rolling applications" if opp.get("deadline") == "rolling" else "Apply by " + str(opp.get("deadline", ""))
    return (f'<article class="opportunity-card"><div class="opportunity-top">{rank_text}'
            f'<span>{esc(opp.get("type", "opportunity").capitalize())}</span><span class="fit-score">{esc(match.get("score", 0))}<small>/100 fit</small></span></div>'
            f'<p class="org-name">{esc(opp.get("org", ""))}</p><h3>{esc(title)}</h3>'
            f'<p class="opportunity-description">{esc(opp.get("description") or "Review the source page for the complete program details and application requirements.")}</p>'
            f'<div class="opportunity-facts"><span>{icon("calendar", 18)}{esc(deadline)}</span>'
            f'<span>{icon("clock", 18)}{esc(opp.get("effort_hours", 0))} h preparation</span></div>'
            f'<p class="eligibility-note">{esc(label)}</p></article>')
