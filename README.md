# Opportunity Intelligence Network

Opportunity Intelligence Network is a planned Streamlit app that helps students find and prepare for internships, scholarships, hackathons, competitions, and workshops. A student provides a profile; five collaborating agents find relevant opportunities, verify listings, assess eligibility and skill gaps, and create a ranked application plan.

> **Project status:** This repository is currently a scaffold. The Python modules and agent files are empty or placeholders, `data/opportunities.json` has no records, `requirements.txt` is not populated with dependencies, and the test files do not yet contain tests. The workflow below describes the agreed target behavior; the app is not ready to run end-to-end.

## How the workflow is designed

```text
Student profile
       |
       +---- Scout: find relevant opportunities ----+
       |                                             |  parallel
       +---- Profiler: structure and score profile --+
                          |
                    Verifier: reject unsafe, expired, or incomplete listings
                      |  may send doubtful listings to Scout once
                    Matcher: check eligibility, fit, and skill gaps
                      |
                    Coach: rank matches and draft a preparation plan
                      |  may ask Matcher to rerank once for a deadline clash
                    Results: ranked plan, checklist, tips, and agent message log
```

The agents share one state object and append to a visible message log. Scout and Profiler run in parallel. Verifier and Coach can each initiate at most one feedback loop. Eligibility, deadlines, clash detection, and numerical scores are determined by code; an LLM is used for text parsing and explanations, not as the source of truth for those decisions.

## Agents

| Agent | Responsibility |
|---|---|
| **Scout** | Find candidate opportunities by student interests and opportunity type; re-check only the requested IDs when challenged by Verifier. |
| **Verifier** | Reject expired, incomplete, untrusted, fee-charging, or suspicious listings; flag stale or near-deadline listings for review. |
| **Profiler** | Turn the student's pasted text into a structured profile and provide a strength score with notes. |
| **Matcher** | Apply year, GPA, field, and nationality rules; score fit and identify skill gaps. Reply to Coach's one-time reranking request. |
| **Coach** | Rank eligible matches by deadline and effort, detect deadline clashes, and prepare a weekly checklist and improvement tips. |

Each agent follows the `agent(state) -> dict` contract: return only the state keys it owns and any new messages. Failures should be reported in the message log, with safe defaults so the rest of the graph can continue.

## Data and trust

The demo is designed to use a hand-collected local dataset rather than depend on live scraping. Real opportunity records should include an official source URL and the date they were last checked. Never invent an opportunity. The only non-real entries should be two clearly marked planted test records: one expired and one charging an application fee.

An opportunity record uses this shape:

```json
{
  "id": "opp_001",
  "title": "Opportunity title",
  "org": "Organization name",
  "type": "internship",
  "deadline": "2026-12-15",
  "eligibility": {
    "min_year": 3,
    "min_gpa": 3.0,
    "fields": ["Computer Science"],
    "nationalities": []
  },
  "required_skills": ["Python", "SQL"],
  "effort_hours": 6,
  "application_fee": false,
  "source_url": "https://official-source.example/opportunity",
  "last_checked": "2026-11-05",
  "planted": false
}
```

The URL above is illustrative, not a real listing. Valid types are `internship`, `scholarship`, `hackathon`, `competition`, and `workshop`. Use `"rolling"` for an opportunity without a fixed deadline. Dates use `YYYY-MM-DD`; the current date should come from `config.TODAY`.

The structured profile contains a name, year, field, GPA, nationality, skills, interests, projects, `strength_score` (0–100), and `strength_notes`. A match contains an opportunity ID, eligibility result and reasons, a fit score and reasons, and skill gaps with explanations. The plan contains ranked opportunity IDs, ranks, deadlines and rationale, plus a weekly checklist and improvement tips.

## Listing checks and matching rules

- Reject opportunities whose deadline has passed, required details are missing, the source URL is missing or unofficial, or scam signals are present (including application fees or guaranteed-selection claims).
- Flag listings last checked more than 30 days ago or with a deadline within 3 days as doubtful. A doubtful listing may be returned to Scout once for re-check.
- When offline, skip URL checks rather than rejecting a listing solely because it could not be reached.
- Check year, GPA, field, and nationality in code, and explain each failed eligibility rule.
- Calculate fit from skill overlap, interest match, and profile strength. Compare required skills with the student's skills and use `data/skill_map.json` to explain gaps.
- Rank eligible matches by deadline and effort. Deadlines within 5 days that exceed the student's available weekly hours count as a clash; Coach may ask Matcher to rerank once.

All LLM calls should go through `llm.py`. The intended provider order is Gemini, a configured secondary provider, then Ollama, followed by a plain-code fallback. Missing keys or provider failures should produce a friendly message and not prevent the local-data workflow from finishing. Replay mode should play a saved run without API calls.

## Project layout

```text
.
├── app.py
├── replay.py
├── state.py
├── graph.py
├── config.py
├── llm.py
├── agents/
│   ├── scout.py
│   ├── verifier.py
│   ├── profiler.py
│   ├── matcher.py
│   └── coach.py
├── data/
│   ├── opportunities.json
│   ├── skill_map.json
│   └── sample_students/
├── cache/
├── tests/
├── .env
├── requirements.txt
└── README.md
```

## Setup (intended)

The planned stack is Python 3.10+, LangGraph, Streamlit, Gemini via `google-genai`, `python-dotenv`, and `pytest`.

On Windows, create and activate a virtual environment:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install langgraph streamlit google-genai python-dotenv pytest
```

Create a local `.env` file in the project root and configure the Gemini key and model used by `llm.py`. Add any secondary-provider credentials only if that provider is implemented. Set `REPLAY_MODE=false` for a normal run. Keep API keys out of source code and do not commit `.env`.

Once `app.py`, the graph, and dependencies have been implemented, the intended commands are:

```powershell
streamlit run app.py
pytest
```

These commands are not expected to provide a working app or meaningful test results with the current scaffold.

## Expected edge-case behavior

- Empty profile input does not start a run; repeated clicks do not start duplicate runs.
- The app can finish from the local dataset without network access and shows an offline notice.
- Missing interests use sensible defaults; no candidate or no eligible match produces a clear explanation instead of a crash.
- Missing year or GPA is treated as unknown and noted in the log.
- Expired and fee-charging entries are rejected with reasons; doubtful entries are re-checked at most once.
- Provider failures fall back in order to another provider and then plain-code behavior. Replay runs without API calls.
- An agent error is logged and should not stop the rest of the graph.

## Tests and demo

The planned pytest suite covers graph loops, each agent's behavior, and a smoke test. The three sample profiles are intended to cover the demo student, a strong profile, and a weaker profile.

The three-minute demo uses Student A: a third-year Computer Science student with a 3.3 GPA, Python, basic machine learning and HTML skills, one class project, and interests in AI internships and scholarships. Show Scout and Profiler running in parallel, Verifier's rejection and re-check messages, Matcher results and skill gaps, then Coach's ranked top-three plan. Use replay mode for a reliable presentation and keep a backup recording.

## Team ownership

Keep changes to another member's owned files coordinated with that owner. The planned primary ownership is:

| Member | Primary work |
|---|---|
| M1 | Scout, shared state, graph, config, graph and Scout tests; main branch integration |
| M2 | Verifier, verifier tests, smoke test, quality assurance |
| M3 | Profiler, Streamlit UI, replay, sample profiles, related tests |
| M4 | Matcher, LLM wrapper, skill map, matcher tests |
| M5 | Coach, Coach tests, README, demo and presentation |

Use one branch per member and merge into `main` when the work runs. Commit small changes and test the owned component before merging. If time is limited, cut live fetching first, then the Coach-to-Matcher loop, then hackathons and workshops. Do not cut verification, the visible message log, or replay mode.
