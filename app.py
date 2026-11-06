"""Futurist: an accessible, local-first student opportunity workspace."""
import json
from uuid import uuid4

import streamlit as st

import config
import replay
from agents.profiler import run as parse_profile
from domain import safe_url
from runtime import drain, empty_view, launch, plan_markdown, task_key
from ui.components import AGENTS, agent_cards, conversation, esc, notice, opportunity_card, section
from ui.icons import icon

st.set_page_config(page_title="Futurist · Your next opportunity", layout="wide", initial_sidebar_state="collapsed")
st.html("<style>" + (config.BASE_DIR / "ui/styles.css").read_text(encoding="utf-8") + "</style>")

ss = st.session_state
DEFAULTS = {"session_id": None, "run": None, "running": False, "view": None, "last_journal": [],
            "view_token": None, "is_replay": False, "form_error": "", "student_text": "",
            "guided_name": "", "guided_year": "Not provided", "guided_field": "", "guided_gpa": "",
            "guided_nationality": "", "guided_skills": "", "guided_interests": "", "guided_projects": "",
            "entry_mode": "Paste a profile", "sample_profile": "Write my own", "step_view": True,
            "opportunity_types": ["Internships", "Scholarships", "Hackathons"], "weekly_hours": 10,
            "focus_areas": "", "use_llm": bool(config.ENABLE_LLM and (config.GROQ_API_KEY or config.OLLAMA_MODEL)), "auto_replay": config.REPLAY_MODE}
for key, value in DEFAULTS.items():
    if key not in ss:
        ss[key] = value
if ss.session_id is None:
    ss.session_id = uuid4().hex
if ss.view is None:
    ss.view = empty_view()

SAMPLES = {"Ayesha · Computer Science": "student_a.txt", "Rayan · Final year": "strong.txt", "Sara · Starting out": "weak.txt"}
TYPE_VALUES = {"Internships": "internship", "Scholarships": "scholarship", "Hackathons": "hackathon",
               "Competitions": "competition", "Workshops": "workshop"}


def fill_profile(text):
    ss.student_text = text
    profile = parse_profile({"student_input": text})["profile"]
    for key in ("name", "field", "nationality"):
        ss["guided_" + key] = profile.get(key) or ""
    ss.guided_year = str(profile["year"]) if profile.get("year") else "Not provided"
    ss.guided_gpa = str(profile["gpa"]) if profile.get("gpa") is not None else ""
    for key in ("skills", "interests", "projects"):
        ss["guided_" + key] = ("; " if key == "projects" else ", ").join(profile.get(key, []))


def choose_example():
    if ss.sample_profile in SAMPLES:
        fill_profile((config.SAMPLE_STUDENTS_DIR / SAMPLES[ss.sample_profile]).read_text(encoding="utf-8"))


def start(text="", *, recording=None, recorded_events=None):
    if ss.running:
        return
    ss.view = empty_view()
    ss.view_token = uuid4().hex
    ss.is_replay = bool(recording or recorded_events)
    ss.form_error = ""
    ss.running = True
    ss.run = launch(text, namespace=ss.session_id, recording=recording, recorded_events=recorded_events,
                    options={"weekly_hours": ss.weekly_hours,
                             "opportunity_types": [TYPE_VALUES[value] for value in ss.opportunity_types],
                             "interests_override": [value.strip() for value in ss.focus_areas.split(",") if value.strip()],
                             "use_llm": ss.use_llm})


st.html(f'<header class="topbar"><a class="brand" href="#">{icon("brand", 34)}futurist</a>'
        '<nav aria-label="Main navigation"><a href="#workspace">Workspace</a><a href="#how-it-works">How it works</a>'
        '<a class="nav-cta" href="#results">Your plan</a></nav></header>')
st.html('<section class="hero"><div><p class="eyebrow">A LITTLE DIRECTION GOES A LONG WAY</p>'
        '<h1>Your potential.<br><em>Your next move.</em></h1>'
        '<p class="hero-copy">Find student opportunities that fit your strengths, understand what it takes, and make a plan you can follow.</p>'
        f'<a class="hero-link" href="#workspace">Let’s find your next step {icon("arrow", 19)}</a></div>'
        '<aside class="hero-aside"><p class="aside-label">Good opportunities deserve a thoughtful plan.</p>'
        f'<div class="hero-illustration" aria-hidden="true"><div class="illustration-block one">{icon("book", 28)}</div>'
        f'<div class="illustration-block two">{icon("briefcase", 28)}</div><div class="illustration-block three">{icon("flag", 28)}</div>'
        f'<div class="illustration-square">{icon("arrow", 25)}</div></div>'
        '<div class="aside-caption"><h3>A clearer path<br>starts with you.</h3><p>Five agents turn your experience into practical next steps.</p></div></aside></section>')

st.html(section("YOUR WORKSPACE", "Start with you.", "Tell us where you are. Your team will help you work out what comes next.", anchor="workspace"))
input_col, team_col = st.columns([0.88, 1.12], gap="large")
with input_col:
    with st.container(key="profile_panel"):
        st.html(f'<div class="panel-title">{icon("person", 23)}Your starting point</div>'
                '<p class="panel-copy">Your year, interests and experience help the team find a better fit.</p>')
        st.selectbox("Start from an example", ["Write my own", *SAMPLES], key="sample_profile", on_change=choose_example,
                     disabled=ss.running)
        st.segmented_control("Profile format", ["Paste a profile", "Guided fields"], key="entry_mode", disabled=ss.running,
                             label_visibility="collapsed")
        with st.container(key="profile_fields"):
            if ss.entry_mode == "Guided fields":
                st.text_input("Name", key="guided_name", placeholder="How should we address you?")
                a, b = st.columns(2)
                a.selectbox("Study year", ["Not provided", *map(str, range(1, 11))], key="guided_year")
                b.text_input("GPA (0–4, optional)", key="guided_gpa", placeholder="e.g. 3.3")
                st.text_input("Field of study", key="guided_field", placeholder="e.g. Computer Science")
                st.text_input("Nationality (optional)", key="guided_nationality", placeholder="e.g. Pakistani")
                st.text_input("Skills", key="guided_skills", placeholder="Python, HTML, machine learning")
                st.text_input("Interests", key="guided_interests", placeholder="AI internships, scholarships")
                st.text_area("Projects and experience", key="guided_projects", height=100,
                             placeholder="Name a project and what you contributed.")
            else:
                st.text_area("Tell us about yourself", key="student_text", height=205,
                             placeholder="I'm a third-year Computer Science student with a 3.3 GPA.\nSkills: Python, HTML, basic machine learning.\nI built a quiz app. I'm interested in AI internships and scholarships.")
            st.multiselect("What would you like to explore?", list(TYPE_VALUES), key="opportunity_types")
            st.number_input("Hours available each week", min_value=0, max_value=80, step=1, key="weekly_hours",
                            help="Preparation hours you can commit, alongside your classes and other work.")
            st.text_input("Focus areas (optional)", key="focus_areas", placeholder="e.g. AI, sustainability, research",
                          help="Separate focus areas with commas. Leave blank to use the interests in your profile.")
            st.checkbox("Add optional language assistance", key="use_llm",
                        disabled=not bool(config.GROQ_API_KEY or config.OLLAMA_MODEL),
                        help="Uses a configured provider for profile text and study tips. Local matching and scheduling always work without it.")
            submitted = st.button("Find my opportunities", type="primary", width="stretch", disabled=ss.running, key="start_analysis")
        if submitted:
            ss.form_error = ""
            if ss.entry_mode == "Guided fields":
                from domain import number
                gpa = ss.guided_gpa.strip()
                if gpa and (number(gpa) is None or not 0 <= number(gpa) <= 4):
                    ss.form_error = "Enter a GPA from 0 to 4, or leave it blank."
                pairs = [("Name", ss.guided_name), ("Year", "" if ss.guided_year == "Not provided" else ss.guided_year),
                         ("Field", ss.guided_field), ("GPA", gpa), ("Nationality", ss.guided_nationality),
                         ("Skills", ss.guided_skills), ("Interests", ss.guided_interests), ("Projects", ss.guided_projects)]
                text = "\n".join(f"{key}: {value}" for key, value in pairs if value.strip())
            else:
                text = ss.student_text.strip()
                ss.form_error = ""
            if not text:
                ss.form_error = "Add a few profile details or choose an example before starting."
            elif not ss.opportunity_types:
                ss.form_error = "Choose at least one opportunity type to explore."
            if not ss.form_error:
                start(text)
                st.rerun()
        if ss.form_error:
            st.html(notice("A little more detail", ss.form_error, tone="sand"))
        st.caption("Uses a local catalog. You stay in control of what you apply for.")
        if replay.load_run("demo"):
            if st.button("Watch an example walkthrough", width="stretch", disabled=ss.running):
                start(recording="demo")
                st.rerun()
        if ss.last_journal:
            if st.button("Replay my last analysis", width="stretch", disabled=ss.running):
                start(recorded_events=list(ss.last_journal))
                st.rerun()

if ss.auto_replay:
    ss.auto_replay = False
    start(recording="demo")

with team_col:
    with st.container(key="team_panel"):
        st.html(f'<div class="team-heading"><div><h3>A team in your corner.</h3>'
                f'<p>Five perspectives. One shared plan. See the work and the conversation.</p></div>{icon("layers", 28)}</div>')
        st.toggle("Follow the work step by step", key="step_view", disabled=ss.running,
                  help="Walk through real recorded events at a readable pace. You can open completed results immediately.")

        @st.fragment(run_every=0.4 if ss.running else None)
        def live_workspace():
            run = ss.run
            if run is not None and ss.running:
                finished = drain(run, ss.view, limit=1 if ss.step_view else None)
                if run.done.is_set() and not finished:
                    st.caption("Your analysis has finished. Walking through your team’s recorded steps.")
                    if st.button("Open results now", width="stretch"):
                        drain(run, ss.view)
                        finished = True
                elif not run.done.is_set():
                    st.caption("Your team is working. Activity and handoffs appear as they happen.")
                if finished:
                    ss.running = False
                    if not ss.is_replay and run.final:
                        ss.last_journal = list(run.journal)
                    st.rerun()
            if ss.is_replay and (ss.running or ss.view.get("final")):
                st.caption("Recorded walkthrough. Dates and availability reflect the saved run.")
            st.html(agent_cards(ss.view))
            st.html(f'<div class="conversation-heading"><h3>The team conversation</h3>{icon("chat", 22)}</div>')
            a, b = st.columns(2)
            agent = a.selectbox("Conversation filter", ["All agents", *[name.capitalize() for name in AGENTS]],
                                label_visibility="collapsed", key="conversation_agent")
            scope = b.selectbox("Message scope", ["Agent handoffs", "All messages"], label_visibility="collapsed", key="conversation_scope")
            st.html(conversation(ss.view["messages"], agent=agent, all_messages=scope == "All messages"))
            if run and run.error:
                st.html(notice("We need to try again", run.error, tone="rose"))
            if run and run.warning:
                st.html(notice("Your results are ready", run.warning, tone="sand"))

        live_workspace()


def match_details(opp, match):
    with st.expander("Fit, eligibility & next steps"):
        st.html('<p class="detail-label">Why this matches</p>' + ''.join(
            f'<p class="detail-text">{esc(reason)}</p>' for reason in match.get("score_reasons", [])))
        st.html('<p class="detail-label">Eligibility to confirm</p>' + ''.join(
            f'<p class="detail-text">{esc(reason)}</p>' for reason in match.get("eligibility_reasons", [])))
        for warning in opp.get("verification_warnings", []):
            st.html(f'<p class="detail-text">{esc(warning)}</p>')
        st.caption(f"Catalog check date: {opp.get('last_checked', 'unknown')}. Source page has not been checked live.")
        gaps = match.get("gaps", [])
        if gaps:
            st.html('<p class="detail-label">Build these skills</p>')
            for gap in gaps:
                st.html(f'<div class="detail-group"><strong>{esc(gap["skill"])}</strong>'
                        f'<p class="detail-text">{esc(gap.get("learn") or gap.get("reason", ""))}</p></div>')
                if safe_url(gap.get("resource")):
                    st.link_button("Learn " + gap["skill"], gap["resource"], width="stretch")
        else:
            st.caption("No skill gaps against the recorded requirements. Check the full program rules on the source page.")


final = ss.view.get("final")
if final and not ss.running:
    profile, plan = final.get("profile", {}), final.get("plan", {})
    matches = final.get("matches", [])
    by_id = {opp["id"]: opp for opp in final.get("verified", []) if isinstance(opp, dict) and opp.get("id")}
    match_by_id = {match["opportunity_id"]: match for match in matches}
    potential = sum(match.get("eligibility_status") != "ineligible" for match in matches)
    st.html(section("YOUR NEXT CHAPTER", "A clearer way forward.", "A shortlist with reasons, a realistic schedule, and room to grow.", anchor="results"))
    if final.get("failures"):
        st.html(notice("This analysis needs attention", "Some work could not complete: " + ", ".join(sorted(set(final["failures"])))
                       + ". Review the conversation and try again before relying on the plan.", tone="rose"))
    with st.container(key="results_summary"):
        st.html('<div class="outcome-summary"><div class="summary-intro"><h3>' + esc(profile.get("name", "Student"))
                + ', start here.</h3><p>Based on your last analyzed profile.</p></div>'
                f'<div><div class="stat-value">{potential}</div><div class="stat-label">potential matches</div></div>'
                f'<div><div class="stat-value">{len(plan.get("ranked", []))}</div><div class="stat-label">practical priorities</div></div>'
                f'<div class="summary-extra"><div class="stat-value">{esc(plan.get("total_hours", 0)):s}</div><div class="stat-label">preparation hours</div></div></div>')
    shortlist_tab, plan_tab, profile_tab = st.tabs(["Your shortlist", "Weekly plan", "Profile & skills"])
    with shortlist_tab:
        st.caption("These listings passed local catalog checks. Confirm current rules, fees and closing times on the source before applying.")
        ranked = plan.get("ranked", [])
        if ranked:
            with st.container(key="priority_cards"):
                cols = st.columns(len(ranked), gap="medium")
                for col, item in zip(cols, ranked):
                    oid = item["opportunity_id"]
                    opp, match = by_id.get(oid, item), match_by_id.get(oid, item)
                    with col:
                        st.html(opportunity_card(opp, match, item["rank"]))
                        if safe_url(opp.get("source_url")):
                            st.link_button("View opportunity", opp["source_url"], width="stretch")
                        match_details(opp, match)
        else:
            st.html(notice("Let’s find a better starting point", "No application fits the current requirements and preparation budget. "
                           "Review the matches, complete missing profile details, or adjust your weekly hours.", symbol="search"))
        with st.expander(f"Explore all {len(matches)} assessed opportunities"):
            a, b = st.columns([1.2, 1])
            search = a.text_input("Search matches", placeholder="Opportunity or organization", key="match_search")
            filt = b.selectbox("Eligibility", ["Potential matches", "Meets recorded rules", "Needs confirmation", "Outside requirements"])
            statuses = {"Potential matches": {"eligible", "conditional"}, "Meets recorded rules": {"eligible"},
                        "Needs confirmation": {"conditional"}, "Outside requirements": {"ineligible"}}[filt]
            filtered = [m for m in matches if m.get("eligibility_status") in statuses
                        and search.lower() in (by_id.get(m["opportunity_id"], {}).get("title", "") + " "
                                               + by_id.get(m["opportunity_id"], {}).get("org", "")).lower()]
            if not filtered:
                st.caption("No opportunities match this view. Try another filter or search.")
            for offset in range(0, len(filtered), 2):
                for col, match in zip(st.columns(2), filtered[offset:offset + 2]):
                    opp = by_id[match["opportunity_id"]]
                    with col:
                        st.html(opportunity_card(opp, match))
                        if safe_url(opp.get("source_url")):
                            st.link_button("Open source page", opp["source_url"], width="stretch")
                        match_details(opp, match)
    with plan_tab:
        st.html(notice("A plan that respects your time", f"Your budget is {plan.get('weekly_hours', 'unspecified')} hours per week. "
                       "Hours are spread evenly across the week, over up to four weeks and ahead of recorded deadlines. Confirm eligibility before investing in a conditional match.", symbol="calendar"))
        weeks = plan.get("weekly_checklist", [])
        for offset in range(0, len(weeks), 2):
            for col, week in zip(st.columns(2), weeks[offset:offset + 2]):
                with col:
                    with st.container(key=f"week_{week['week']}"):
                        st.html(f'<div class="week-header"><div><h3>Week {week["week"]}</h3>'
                                f'<p>{esc(week.get("starts", final.get("run_date", "")))}</p></div>'
                                f'<span class="week-hours">{week.get("hours", 0):.1f} h planned</span></div>')
                        for task in week.get("tasks", []):
                            st.checkbox(task, key=task_key(ss.view_token or final.get("run_id", ""), week["week"], task))
        if not weeks:
            st.caption("Add weekly availability and rerun your profile to build a schedule.")
        if plan.get("deferred"):
            with st.expander("Opportunities to revisit when you have more time"):
                for item in plan["deferred"]:
                    st.html(f'<div class="detail-group"><strong>{esc(item["title"])}</strong><p class="detail-text">{esc(item["reason"])}</p></div>')
        st.html(section("KEEP MOVING", "Small improvements, stronger applications."))
        for tip in plan.get("improvement_tips", []):
            st.html(f'<div class="strength-note">{esc(tip)}</div>')
    with profile_tab:
        a, b = st.columns([0.9, 1.1], gap="large")
        with a:
            st.html(f'<div class="profile-summary">{icon("person", 30)}<h3>{esc(profile.get("name", "Student"))}</h3>'
                    f'<p>{esc(profile.get("field") or "Field not provided")}</p>'
                    f'<p>Year {esc(profile.get("year") or "not provided")} · GPA {esc(profile.get("gpa") if profile.get("gpa") is not None else "not provided")}</p>'
                    f'<p>{esc(profile.get("nationality") or "Nationality not provided")}</p>'
                    f'<div class="skill-list">' + ''.join(f'<span>{esc(skill)}</span>' for skill in profile.get("skills", [])) + '</div></div>')
            st.button("Use this profile in the workspace", on_click=fill_profile, args=(final.get("student_input", ""),), width="stretch")
            st.caption("Make corrections in the workspace, then analyze again to update your plan.")
        with b:
            st.html(f'<div class="panel-title">Profile strength · {profile.get("strength_score", 0)}/100</div>'
                    '<p class="panel-copy">A preparation guide based on named skills, projects, GPA and study year. This is not an admission prediction.</p>')
            for note in profile.get("strength_notes", []):
                st.html(f'<div class="strength-note">{esc(note)}</div>')
            if profile.get("missing_fields"):
                st.html(notice("A few details are still missing", ", ".join(profile["missing_fields"]) + ". Affected matches remain conditional.", tone="sand"))
        if profile.get("projects"):
            st.html('<p class="detail-label">Your project evidence</p>' + ''.join(
                f'<div class="strength-note">{esc(project)}</div>' for project in profile["projects"]))
    with st.expander(f"Review the {len(final.get('rejected', []))} excluded listings"):
        for opp, reason in final.get("rejected", []):
            st.html(f'<div class="detail-group"><strong>{esc(opp.get("title", "Listing"))}</strong><p class="detail-text">{esc(reason)}</p></div>')
        if not final.get("rejected"):
            st.caption("No candidates were excluded by the catalog checks in this run.")
    a, b = st.columns(2)
    a.download_button("Download my plan", plan_markdown(final), file_name="futurist-plan.md", mime="text/markdown", width="stretch")
    b.download_button("Download full results", json.dumps(final, ensure_ascii=False, indent=2),
                      file_name="futurist-results.json", mime="application/json", width="stretch")

st.html(section("A THOUGHTFUL PROCESS", "A little context changes everything.", anchor="how-it-works"))
st.html('<div class="how-grid">'
        f'<article class="how-card">{icon("person", 28)}<h3>More than a list of skills.</h3><p>Share your studies, interests and projects. Scout and Profiler work together to understand where you want to go.</p></article>'
        f'<article class="how-card">{icon("shield", 28)}<h3>Good reasons, clearly explained.</h3><p>Verifier checks the catalog evidence. Matcher explains fit, missing skills and the requirements you still need to confirm.</p></article>'
        f'<article class="how-card">{icon("calendar", 28)}<h3>Next steps that fit your week.</h3><p>Coach turns your shortlist into a preparation schedule. When deadlines compete, the team revisits your priorities.</p></article></div>'
        '<div class="page-footer"><span>futurist · Opportunity Intelligence Network</span><span>Built for your next chapter.</span></div>')
