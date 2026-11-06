# Futurist

**A clearer path from your student profile to your next opportunity.**

Futurist is the Opportunity Intelligence Network: a Streamlit workspace where five agents find relevant student opportunities, check catalog evidence, explain eligibility and skill gaps, and build a preparation plan around your weekly availability.

The full local workflow works without an API key. It includes a light interface, local SVG icons, a guided profile builder, real agent activity and conversations, source links, a weekly checklist, downloads, and offline replay.

## Run locally

Use **Python 3.12**. The tested Windows environment is Python 3.12.14. `requirements.lock` pins the full dependency environment; `requirements.txt` lists the direct dependencies.

From the repository in PowerShell, using [uv](https://docs.astral.sh/uv/):

```powershell
uv venv --python 3.12 .venv
uv pip sync --python .venv\Scripts\python.exe requirements.lock
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Open **http://localhost:8501**. No `.env` file is needed for local analysis or replay.

With a conventional Python installation, the equivalent setup is:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m streamlit run app.py
```

On macOS/Linux, use `python3.12 -m venv .venv` and `.venv/bin/python` in place of the Windows interpreter path.

## Use the workspace

1. Paste a profile, use the guided fields, or choose one of the synthetic examples.
2. Select opportunity types and enter the preparation hours you can commit each week. Focus areas are optional.
3. Choose **Find my opportunities**. The workspace shows each agent starting, completing, and handing findings to another agent.
4. Open **Your shortlist** for source links, fit explanations, eligibility conditions, and learning resources.
5. Open **Weekly plan** for priorities, preparation dates, capacity limits, deferred opportunities, and checkable tasks.
6. Review **Profile & skills** and correct your inputs before rerunning if anything is missing.
7. Download your plan as Markdown or the full results as JSON. Replay your last analysis within the same session, or watch the bundled synthetic walkthrough.

The step-by-step view presents actual execution events at a readable pace. If computation finishes before the walkthrough, the UI says so and offers **Open results now**. It does not delay agent computation or simulate extra work. Agent cards use readable state text and solid surfaces rather than status dots or progress bars. The conversation can be filtered by agent and by handoffs/all messages.

## How the agents work

```text
                    Student profile + preferences
                              |
               +--------------+--------------+
               |                             |
             Scout                        Profiler
               |                             |
               +--------------+--------------+
                              |
                           Verifier
                        /             \
             one catalog reread       checked candidates
                 via Scout                    |
                                           Matcher
                                              |
                                            Coach
                                              |
                       one priority review via Matcher
                                              |
                        Shortlist + preparation schedule
```

| Agent | What it contributes |
| --- | --- |
| **Scout** | Searches the local catalog by interests and selected types, deduplicates source identities before the candidate cap, ranks relevance, and rereads only challenged records. |
| **Profiler** | Parses labelled text and prose, preserves section boundaries, normalizes skills, identifies missing evidence, and computes a transparent strength score. Optional model assistance can fill grounded text spans, not invent qualifications. |
| **Verifier** | Validates records independently, rejects expired/fee/unsafe/suspicious entries, checks actual URL hosts, and preserves stale-source or imminent-deadline warnings after its single feedback round. |
| **Matcher** | Applies recorded study-year/GPA/field/nationality rules, distinguishes confirmed/conditional/ineligible outcomes, explains fit and skill gaps, and responds to Coach's priority challenge. |
| **Coach** | Prioritizes by deadline, effort and fit; asks for one review when close deadlines compete; selects up to three practical priorities and allocates preparation within the stated weekly hours. Infeasible preparation is deferred explicitly. |

The graph waits for both Scout and Profiler before starting Verifier. Each agent emits real start/completion/failure events. A guarded boundary isolates failures, validates output shapes and ownership, and prevents mutation of shared input. Missing or broken production agents produce visible failures; they never silently become fake agents. `agents/stubs.py` remains an explicit test fixture only.

## What the recommendations mean

- **Meets recorded rules:** supplied profile evidence satisfies every structured rule available for that listing. This is not a decision by the program or a guarantee of admission.
- **Confirm eligibility:** required profile facts, full program rules, or source freshness still need confirmation. These can appear as conditional priorities; checking the source is the first action.
- **Outside recorded requirements:** at least one explicit rule fails. These never enter the application plan.

Fit combines recorded skill overlap (50%), interest relevance (30%), and profile strength (20%). Distinct skills such as Java and JavaScript are not interchangeable. Undocumented skill requirements receive a neutral score. The strength score summarizes named skills, projects, GPA and study year; it does not predict selection.

Schedules spread the provided weekly hours evenly over seven days, across a maximum of four weeks. Estimated preparation must finish by each recorded deadline. These estimates describe preparation work, not a program's duration or an official required workload. Conditional priorities start with eligibility/source confirmation. Weekly capacity is not inferred when absent from direct agent input.

## Catalog and trust boundaries

`data/opportunities.json` contains **42 records**: 19 hackathons, 12 scholarships and 11 internships. Two are explicitly planted rejection fixtures: one expired and one fee-charging. Scout deduplicates a repeated source identity, so the runtime catalog has 41 unique source records before filtering. There are currently no workshop/competition records; selecting those alone produces an honest empty result.

The catalog is local and manually maintained. **The app does not scrape the web or independently verify source pages.** A local reread never becomes proof of fresh official verification. Source URLs, deadlines and requirements must be confirmed on the linked pages before applying. The unplanted catalog entries explicitly mark full eligibility as incomplete; their recommendations remain conditional until those details are confirmed. Existing program dates, fees and commercial claims have not been independently revalidated during this repair.

Validate the catalog with:

```powershell
.\.venv\Scripts\python.exe -m scripts.validate_data
```

Warnings about incomplete eligibility and the duplicate source are intentional and visible. Structural errors cause a nonzero exit code. Invalid records are rejected individually at runtime so one bad listing does not discard valid peers.

## Optional language assistance

Copy `.env.example` to `.env` only if you want a model provider. Keep `.env` local; it is ignored by Git.

| Setting | Purpose |
| --- | --- |
| `GROQ_API_KEY`, `GROQ_MODEL` | Optional Groq API credentials and primary model. |
| `GROQ_FALLBACK_MODEL` | Backup Groq model, tried after the primary model fails. |
| `OLLAMA_MODEL`, `OLLAMA_URL` | Optional configured Ollama provider after Groq. No local service is contacted unless configured and assistance is enabled. |
| `ENABLE_LLM` | Default preference for the UI's optional language-assistance control. It stays off without a configured provider. |
| `LLM_TIMEOUT`, `LLM_RETRIES` | Per-request timeout and retry count. Temporary transport/rate-limit errors use bounded retries; failed providers fall through to the next provider. |
| `LLM_TEMPERATURE`, `LLM_MAX_TOKENS` | Generation settings passed to configured providers. |
| `TODAY_OVERRIDE` | Optional `YYYY-MM-DD` date for reproducible demonstrations. Otherwise uses the current Asia/Karachi date at process startup; restart a long-running server after a date change. |
| `REPLAY_MODE` | Automatically opens the bundled synthetic walkthrough in each new browser session. It makes no agent/provider calls. |

All model calls go through `llm.py`. Models can help with grounded text parsing and study suggestions; they do not certify listings, decide eligibility, change deadlines or override the deterministic schedule. Provider failure leaves the local workflow available. Turning on assistance sends the supplied text/gap context to the configured provider; leave it off to keep analysis local.

## Replay and local records

- `cache/demo.json` is a versioned, explicitly synthetic recording from the real five-agent pipeline, dated 7 November 2026. Its program details reflect that recording date.
- Browser sessions hold their latest journal in memory. Private disk recordings go to ignored `cache/sessions/<session-id>/last_run.json`, not the shared demo filename.
- Recording names and structures are validated, writes are atomic, and damaged recordings produce a clear error. A save failure leaves completed analysis available for download.
- Session-scoped storage prevents accidental cross-session replay; it is not an account/authentication system. A new browser session does not automatically recover an earlier session's private journal.
- Checklist completion persists through rerenders of the current plan. New analyses and different tasks receive independent completion state.

Regenerate the synthetic walkthrough after changing agent behavior:

```powershell
.\.venv\Scripts\python.exe -m scripts.record_demo
```

This command uses the bundled Student A text and disables model access. It never records the current UI user's profile.

## Tests and development

```powershell
.\.venv\Scripts\python.exe -m pytest -q -ra
.\.venv\Scripts\python.exe -m scripts.validate_data
uv pip check --python .venv\Scripts\python.exe
```

The suite covers each agent, graph loops and joins, real-agent integration, capacity and deadline constraints, malformed data, missing evidence, failure isolation, grounded optional parsing, session-safe recording, and Streamlit input/replay/checklist/export flows. Tests freeze the date and disable external providers. No smoke tests skip obsolete APIs.

GitHub Actions runs the same suite on Windows and Ubuntu with Python 3.12. Browser screenshot/mobile visual review is separate from the automated Streamlit runtime checks; the browser bridge was unavailable during this implementation session.

To update the lock after deliberately changing dependencies:

```powershell
uv pip compile requirements.txt --python-version 3.12 --universal --output-file requirements.lock
```

Important modules:

```text
app.py                 Streamlit workspace and user flows
runtime.py             Background execution, event presentation and exports
graph.py / state.py    LangGraph orchestration, lifecycle events and shared contract
domain.py              Catalog validation and evidence normalization
agents/                Scout, Profiler, Verifier, Matcher and Coach
llm.py                 Optional Groq/Ollama transport and fallback
replay.py               Validated atomic recordings and playback
ui/                    Local SVG icons, HTML components and responsive light styles
data/                  Catalog, skill resources and complete synthetic profiles
tests/                 Agent, regression, integration and Streamlit tests
PROJECT_AUDIT.md       Original 18-finding bug report and remediation status
```

Work is on `ali-haider`; changes are reviewed through a pull request to `main`. This version remains a local student advisor: it does not submit applications, operate user accounts, or provide live web discovery.
