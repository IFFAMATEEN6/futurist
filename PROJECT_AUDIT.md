# Futurist: project analysis and bug report

Audit date: 7 November 2026 (Asia/Karachi). Baseline commit: `45d3b989975d0033f85e4b4b7c66b752d85b173e`. Working branch: `ali-haider`, created from local `main`. Remote branches were inspected locally; no fetch, merge, commit, or push was performed.

This is the baseline audit before repairs. Application behavior has not been changed. Findings below distinguish reproduced failures, source findings, and remaining verification work.

## 1. What the project is trying to do

The product name in the application is **Opportunity Intelligence Network**. Futurist is the repository/folder name. It is a student opportunity advisor: take a student's profile, find relevant opportunities, filter unsafe or unsuitable listings, explain fit and missing skills, and produce a realistic application/preparation plan.

The intended user journey is:

1. Paste a student profile and provide interests and time available.
2. Scout searches the local opportunity catalog while Profiler structures the profile.
3. Verifier checks listing quality, deadlines, fees, and source information; doubtful items can return to Scout once.
4. Matcher checks eligibility and computes fit and skill gaps.
5. Coach chooses priorities, handles conflicting deadlines through one Matcher feedback round, and prepares a weekly checklist.
6. The student reviews source links, reasons, gaps, and next actions. A saved replay supports demonstrations without model calls.

The useful idea is the connection between discovery and preparation: a student should understand **what to apply for, why it fits, what is uncertain, and what to do next**. The agent architecture should support those decisions with an inspectable log. A sequence of agent completion cards alone does not establish that the recommendations are correct.

This is currently a local-data prototype. Scout does not search the web, and Verifier does not fetch official pages. It has no application submission integration, authentication, per-user database, or application tracking system. Those are possible later features, not prerequisites for repairing the stated local demo.

## 2. Architecture and implementation status

| Area | Implementation | Current assessment |
| --- | --- | --- |
| UI | `app.py`, Streamlit, background worker and event queue | Profile entry, status cards, message log, basic results and replay controls exist. Important decision details are omitted. |
| Orchestration | `graph.py`, LangGraph | Parallel Scout/Profiler branch, join, bounded Verifier and Coach loops, event streaming, cached compilation. |
| Shared contract | `state.py` | Typed dictionaries, append-only message reducer and owned output keys. Runtime schema validation is absent. |
| Scout | `agents/scout.py` | Local JSON index, interest scoring, candidate cap, selected-ID reread. No independent source revalidation. |
| Profiler | `agents/profiler.py` | Regex parsing and deterministic strength score. Model integration imports a nonexistent function. |
| Verifier | `agents/verifier.py` | Rules for dates, required fields, fees, suspicious text and URL substrings, with optional model verdict. Several rules misclassify records. |
| Matcher | `agents/matcher.py` | Year/GPA/field/nationality checks, weighted fit, skill-gap resources, clash score penalty. Unknown eligibility and substring skill matching are unsafe assumptions. |
| Coach | `agents/coach.py` | **Empty file.** Runtime substitutes `agents.stubs.coach`. |
| Model access | `llm.py` | Groq HTTP request, retries for rate limits/invalid JSON, JSON extraction, `(result, note)` API. Only one provider/model is wired. |
| Replay | `replay.py`, `cache/last_run.json` | JSON event playback exists. Shipped recording includes stub agents and a stub plan. |
| Data validation | `scripts/validate_data.py` | Checks basic identity, type, dates and HTTP(S) URL syntax. Does not validate the full runtime schema or run automatically during loading. |
| Tests | `tests/` | Useful unit coverage, fake-agent graph tests, but smoke tests import an obsolete API and Coach/UI replay files contain no tests. |

The README's statement that the modules, dataset, dependencies and tests are empty is outdated. Conversely, the presence of real agent files should not be read as proof that the full product is complete.

### Dataset inventory

- 42 records: 19 hackathons, 12 scholarships, 11 internships.
- 40 unplanted records and two explicitly planted rejection examples.
- No workshop or competition records, although the state contract supports those types.
- `opp_112` and `opp_m2_004` share the same Syntax Summit source URL and have different effort/skill metadata.
- The schema validator returns **0 errors, 0 warnings** on the committed dataset. That establishes only that its limited checks pass.
- Several descriptions explicitly defer age/country eligibility to external rules, while their structured eligibility fields are unrestricted. This is incomplete evidence, not confirmation that all students are eligible.

Official source contents, current availability, prize amounts, deadlines, fees, and country/degree rules have **not** been independently checked in this audit. Dataset `last_checked` fields are repository assertions. They are not audit evidence of current availability.

## 3. Verification baseline

An isolated Python 3.12 environment was prepared outside the repository at `%LOCALAPPDATA%\Codex\venvs\futurist-audit`. The host default Python 3.14 initially lacked Streamlit, LangGraph and Groq; that is an environment prerequisite, not by itself an application defect.

Completed checks:

- Existing Scout, Profiler, Matcher and Verifier suites on host Python: **77 passed** (`python -m pytest tests/test_scout.py tests/test_profiler.py tests/test_matcher.py tests/test_verifier.py -q -ra`).
- Dataset validation and inventory with local code.
- Direct failure probes for multiline parsing, unknown eligibility, skill overlap, malformed listing fields, URL filtering, stale rereads and replay contents.
- Manual Scout → Profiler → Verifier → Matcher execution using Student A with model access disabled: 20 candidates, 15 verified, four rejected and one deferred in the first verification pass; seven matches marked eligible. Legitimate-source listings were among the rejections. This was deliberately a first-pass probe, not a substitute for full graph execution.

Full dependency-environment pytest, real graph execution, and Streamlit runtime results are recorded in section 6.

## 4. Bug register

All items are open at this baseline. P0 means the core promised workflow is incomplete; P1 means recommendations, trust, or validation are materially wrong; P2 means supporting behavior, resilience, or documentation needs repair. These are project priorities, not vulnerability ratings.

### F01 — P0: Coach is absent and silently replaced with demo behavior

**Evidence:** `agents/coach.py` is zero bytes. `graph.load_agent()` substitutes a stub when `run()` is missing or import fails. `agents/stubs.py:coach()` produces `why: "stub"`, `stub task`, `stub tip`, and invents a deadline clash whenever at least two matches exist. Its selection does not filter `eligible`.

**Impact:** The application's final planning stage is a demonstration placeholder. A successful graph completion can produce an ineligible recommendation and cannot substantiate any schedule.

**History:** Commit `8bd13c3` added a root-level `coach.py`; commit `45d3b98` reverted that merge. The runtime imports `agents.coach`, so simply recovering the old root-level file would also require deliberate integration and validation against the current contract.

**Repair:** Implement a real Coach using eligible matches, actual deadlines, effort and explicit weekly capacity. Reserve stubs for explicit tests/demo mode; surface unavailable agents in normal operation.

**Acceptance:** Five real agents load. Ineligible matches never enter the plan. Close deadlines trigger a challenge only when their effort exceeds available time. Each loop stops after its configured limit. Empty matches produce useful guidance without fake opportunities.

### F02 — P1: URL blacklist rejects legitimate domains

**Reproduced:** `_url_looks_unofficial("https://kiroween.devpost.com/rules")` and the Microsoft Leap URL both return `True`. The substring `t.co` occurs inside `devpost.com` and `microsoft.com`. **18 of 42 dataset URLs** match the blacklist. `https://T.CO/abc` bypasses it because the check is case-sensitive.

**Location:** `agents/verifier.py:_url_looks_unofficial`.

**Repair:** Parse and normalize the hostname, compare actual domains/subdomains, and check forms paths separately. Avoid classifying official ownership solely by absence from a blacklist.

**Acceptance:** Devpost/Microsoft sources survive the shortener check; case variants of actual blocked hosts do not. A blocked string in an unrelated URL path does not establish hostname identity.

### F03 — P1: Malformed records pass verification or discard the whole batch

**Reproduced:** A listing with `source_url="javascript:alert(1)"`, `eligibility="broken"`, `application_fee="true"`, or a scam claim only in its description can pass. A candidate missing its `id` raises `KeyError` before required-field validation; a numeric deadline raises `TypeError`. The validator accepts malformed eligibility, a string fee flag, a string skills value and negative effort with zero errors.

**Locations:** `agents/verifier.py:run`, `_has_fee`, `_has_scam_signal`, `_is_expired`; `scripts/validate_data.py:validate_records`; `agents/scout.py:load_index`.

**Impact:** The graph guard can catch a Verifier crash, but that loses verification for otherwise good candidates. Invalid metadata can reach Matcher and invalidate its entire batch too.

**Repair:** Share one complete runtime record validator, reject/quarantine individual bad records, require valid HTTP(S) source URLs, typed eligibility/fee/skills/effort fields, and inspect relevant description text. Keep structural checks active offline.

**Acceptance:** One bad record does not prevent valid peers from being processed; each rejected item has a specific reason. All malformed probes above are handled deliberately.

### F04 — P1: Recheck promotes stale data without fresh evidence

**Reproduced:** A rolling listing with `last_checked="2000-01-01"` is deferred in round zero and verified in round one without changing its date or contents. Scout only copies the same local record; Verifier skips doubt checks whenever `round_v > 0`.

**Locations:** `agents/scout.py:_recheck`; `agents/verifier.py:run`; `graph.py:rescout`.

**Repair:** Track the evidence/outcome of rechecking. Preserve unresolved warnings after the one allowed round; do not equate loop completion with source confirmation. Offline rereads should be labelled honestly.

**Acceptance:** A stale record stays explicitly uncertain until genuine new evidence exists; no infinite loops; already valid records remain available across the loop.

### F05 — P1: Model output controls listing legitimacy

**Reproduced/source:** `_llm_review()` can directly approve or reject doubtful listings based on a free-text verdict. No source fetch provides independent evidence. The same stale synthetic record was verified with a mocked `approve` and rejected with a mocked `reject`, without any other change.

**Location:** `agents/verifier.py:_llm_review`, `run`.

**Repair:** Keep verification status and freshness decisions in deterministic rules. Use model output for explanations only, and make unresolved evidence visible.

**Acceptance:** Changing a mocked model reply between `approve` and `reject` cannot silently change factual verification outcomes without new evidence.

### F06 — P1: Common profile formats parse incorrectly

**Reproduced:** The labelled multiline input in `tests/test_smoke.py` yields `year=None`, empty interests/projects, and skills containing `Html Projects: ... Interests: Ai Internships` and `Scholarships`. `run()` removes newlines before a parser that uses newlines as field boundaries. It also does not recognize `Year: 3`, `Name: Ahmed Ali`, `Projects: ...`, or `Interests: ...` as intended fields.

**Location:** `agents/profiler.py:_parse`, `run`.

**Repair:** Preserve section boundaries, support both labelled profiles and natural prose, normalize aliases, validate numeric ranges, and show the extracted profile for correction.

**Acceptance:** Student A and the smoke-test profile yield the same year/GPA/field/skills/interests meaning; sections never become skills. Missing values remain unknown rather than invented.

### F07 — P1: Unknown eligibility is presented as eligible

**Reproduced:** `check_eligibility({}, opportunity)` returns `True` even when that opportunity requires year 4, GPA 3.9, Medicine and American nationality. Reasons acknowledge missing information, but the boolean still admits the item into eligible ranking. Existing unit tests explicitly expect this behavior for missing year/GPA.

**Location:** `agents/matcher.py:check_eligibility`.

**Repair:** Distinguish confirmed eligible, ineligible and needs-information. Apply this distinction consistently in scoring, Coach selection and UI. Missing data need not mean rejection, but must not mean confirmed eligibility.

**Acceptance:** Missing required profile evidence produces a clear conditional status and requests the relevant fields; a Profiler failure cannot yield an apparently confirmed application plan.

**Failure-path reproduction:** With a synthetic Profiler exception, the real graph still marked eight matches eligible and produced three ranked recommendations. The exception was logged, but did not prevent the misleading eligibility result.

### F08 — P1: Substring skill matching produces false qualifications

**Reproduced:** `has_skill(["JavaScript"], "Java")` and `has_skill(["C++"], "C")` both return `True`.

**Location:** `agents/matcher.py:has_skill`.

**Repair:** Use explicit aliases and normalized proficiency phrases with token boundaries. Keep distinct languages distinct.

**Acceptance:** ML/basic machine learning aliases still work; JavaScript does not satisfy Java, and C++ does not automatically satisfy C. Gaps and fit scores reflect the corrected comparisons.

### F09 — P1: End-to-end tests silently skip the real pipeline

**Evidence:** All six smoke tests call `_load_graph()`, which imports nonexistent `graph.run_graph`; the real entry point is `graph.run`. The helper catches `ImportError` and skips. Further assertions assume rejected entries are dictionaries and verified entries are IDs; runtime contracts instead use `(record, reason)` pairs and full records. `tests/test_coach.py` and `tests/test_ui_replay.py` contain only docstrings. Fake-agent graph tests cannot expose a missing real Coach.

**Repair:** Test the real graph API and actual state shapes. Explicitly disable/mock network/model access in deterministic tests. Fail when a production agent resolves to a stub. Add Coach and UI/replay coverage around actual user workflows.

**Acceptance:** No obsolete-import skips; tests assert real profile fields, planted-record rejection, safe ranking, useful plan contents, both bounded loops, replay without provider access, and agent failures without misleading success.

### F10 — P1: Results omit the information needed to apply

**Source finding:** `app.py` renders profile strength, plan titles/deadlines/effort, checklist, tips and rejected titles. It does not display official source links, full parsed profile, fit score/reasons, eligibility reasons or skill-gap resources from `matches`. Weekly availability is neither collected nor included in shared state.

**Impact:** Students cannot check or open the recommended opportunity from the results, or understand the basis/conditions of the recommendation. Capacity-aware planning cannot use their actual capacity.

**Repair:** Add actionable opportunity results with source links, transparent eligibility and fit, gap resources and editable/correctable profile inputs. Add validated weekly capacity to the state and Coach input.

**Acceptance:** A user can follow a source link, explain why an item was recommended, identify missing requirements, and obtain a schedule based on supplied hours.

### F11 — P2: Shipped replay demonstrates stub results; replay configuration is unused

**Reproduced:** `cache/last_run.json` contains five verified records, no rejections, stub Verifier/Matcher messages and a plan containing `stub task`/`stub tip`. `REPLAY_MODE` is read in `config.py` but never used by the UI/graph. The replay button is enabled if *any* run exists but only starts if `last_run` exists. Streamlit AppTest with `list_runs()` returning only `named_recording` confirmed an enabled replay button whose click starts no run and reports no error.

**Repair:** Generate a labelled demo recording from the repaired real pipeline, distinguish recorded date from current validity, implement or remove the unused environment switch, and select an actual saved recording reliably.

**Acceptance:** Replay works without model/network access, displays a useful real-agent plan and its recording context, and never exposes an enabled no-op button.

### F12 — P2: Profiler model API and configured fallbacks are disconnected

**Reproduced/source:** `profiler.call_llm_json is None` because `llm.py` exposes `ask`, not `call_llm_json`. The failure is swallowed. `PROVIDERS` contains only Groq. `GROQ_FALLBACK_MODEL`, Ollama settings and `config.LLM_TIMEOUT/RETRIES/TEMPERATURE/MAX_TOKENS` do not drive the wrapper's hardcoded behavior. README describes a different provider order (Gemini first).

**Repair:** Choose and document the supported provider contract, route optional parsing through `ask(..., want_json=True)` with schema validation, and honor settings for every implemented provider. Preserve a reliable plain-code path and visible fallback notes.

**Acceptance:** Configured settings take effect, provider failure is visible without blocking offline completion, and optional model parsing cannot overwrite valid data with malformed values.

### F13 — P2: Offline status is disconnected and repeatedly probes the network

**Source finding:** `OpportunityState`, `new_state()` and `graph.stream_events()` do not carry `offline`, although Verifier reads it. The UI only shows a warning. `ss.setdefault("online", is_online())` evaluates `is_online()` on every script rerun, even when the key exists. The probe targets public DNS rather than the configured provider. Replay sets `online=True` but still evaluates that probe on rerun.

**Repair:** Use explicit execution settings and scoped connectivity/provider results. Cache or remove the eager probe, and ensure replay does not invoke it. Local URL syntax and hostname checks do not need connectivity.

**Acceptance:** Offline/replay workflows do not attempt unnecessary provider/probe calls; offline status does not disable structural trust checks.

**Runtime evidence:** During the combined AppTest scenario (initial load, empty input, normal run, checkbox changes, replay), the mocked connectivity probe was called 21 times. Its count increased while replay was running.

### F14 — P2: Replay storage lacks isolation, atomicity and validation

**Reproduced/source:** `_path("../audit_escape")` resolves outside `CACHE_DIR` (path resolution only; no escape file was written). Every normal UI run saves the same shared `last_run` filename, including raw profile text. Saves use direct writes; loads accept arbitrary decoded JSON, and `replay_events()` assumes event structure. A cache write failure is reported by `_worker` as a run failure even after a final graph result was produced.

**Repair:** Restrict recording names, validate payloads, use atomic writes and session-scoped storage, keep user recordings out of Git, and report cache-save failure separately from analysis failure. A deliberately synthetic demo recording can remain versioned.

**Acceptance:** Names cannot escape the cache; malformed/truncated recordings produce a clear replay error; one session cannot overwrite another's recording; a failed save preserves the completed result.

### F15 — P2: Agent guard does not validate returned data

**Reproduced/source:** `guarded("scout", lambda state: ["bad"])(state)` raised `AttributeError: 'list' object has no attribute 'items'`. The guard catches exceptions from `fn(state)` but calls `out.items()` outside that handler. Owned-key filtering also does not validate field types or prevent mutation of nested input state.

**Repair:** Validate the returned mapping and owned-value shapes inside the protected boundary. Define safe failure outputs so stale/incomplete fields are not presented as current success.

**Acceptance:** Malformed output and ordinary exceptions become logged agent failures without breaking streaming or producing fake successful plans.

### F16 — P1: Catalog contains duplicate and incomplete eligibility metadata

**Reproduced/source:** Syntax Summit appears twice under separate IDs with different effort and skills. Some records say eligibility is not checked while structured rules imply open access. Scholarship requirements such as an admission offer, degree level, region, work experience, or age have no consistent structured representation.

**Repair:** Deduplicate by canonical source/event identity, record provenance for eligibility facts and distinguish unknown from unrestricted. Verify official sources before correcting commercial/program facts; preserve uncertainty where evidence is unavailable.

**Acceptance:** One opportunity cannot occupy multiple plan slots through duplicate IDs. Incomplete program rules are visible and never represented as complete eligibility verification.

### F17 — P2: Samples, setup documentation and dependency declarations mislead

**Evidence:** README still calls populated files empty and describes an unimplemented provider stack. Three sample JSON files are `{}`. `strong.txt` claims six skills and three projects without naming them; the parser yields zero of each and strength **31**, below Student A's **53**. `requirements.txt` has no version constraints and includes a Groq SDK while the wrapper uses `urllib` directly. There is no checked-in dependency lock or CI workflow.

**Repair:** Write accurate setup/status documentation, provide complete synthetic profile fixtures, decide the supported Python/dependency versions based on tested installation, and add a reproducible test command/CI after repairs.

**Acceptance:** A clean install and documented commands launch the app and run the real suite; strong/demo/weak fixtures exercise distinct intended cases without invented parsing assumptions.

### F18 — P2: Checklist completion leaks into a different plan

**Reproduced:** In Streamlit AppTest, check the first Week 1 task, replace the final plan's checklist with a completely different Week 1 task, and rerun. The new task is already checked. Widget keys are only `chk_{week}_{index}` and therefore do not identify the run or task.

**Location:** `app.py`, weekly checklist rendering.

**Repair:** Scope checklist state to a stable run/plan identity and task identity. Preserve progress within the same plan and deliberately initialize progress for a new plan.

**Acceptance:** Rerendering one plan preserves its task progress; a different plan or task does not inherit completion by occupying the same week/index.

## 5. Repair order and definition of working

1. **Make failures visible and tests meaningful:** remove implicit production stubs, fix smoke API/contracts, add regression cases for the reproduced failures, and define validated records plus conditional eligibility.
2. **Repair inputs and verification:** profile parsing, host-based URL checks, malformed-record isolation, deterministic trust rules, honest stale/offline outcomes and deduplication.
3. **Complete decisions and planning:** precise skill matching, explicit capacity, a real Coach, deterministic ranking and bounded, meaningful feedback loops.
4. **Complete the user journey:** editable/correctable profile, actionable links and match explanations, useful empty/error states, and checklist state tied to the current plan.
5. **Make demos and setup dependable:** isolated/validated replay storage, real synthetic demo recording, aligned model configuration, updated README, dependency baseline and CI.

The local prototype is working when all five real agents run with **no API key**, Student A produces an explainable plan from eligible or explicitly conditional records, expired/fee records never enter that plan, malformed records do not poison valid peers, application links and skill-gap resources are usable, and replay completes without model/network access. The same flow must handle missing fields, no matches, agent failures and limited weekly capacity without fabricated success.

Live discovery, cloud deployment, accounts and automatic application submission should be separate scope decisions after this baseline works.

## 6. Runtime verification follow-up

Dependency installation completed successfully with Python 3.12.14. The installed direct packages were LangGraph 1.2.20, Streamlit 1.67.0, Groq 1.7.0, python-dotenv 1.2.4 and pytest 9.2.0. These are the observed installation baseline, not a proposed version policy. `pip check` reported no broken requirements.

| Check | Observed result | Meaning |
| --- | --- | --- |
| Full existing pytest suite | **91 passed, 6 skipped**, 2.08 seconds reported by pytest | Six obsolete-API smoke tests skip; passing is not end-to-end acceptance. |
| Dataset validator | 42 records, 0 errors, 0 warnings | Current limited validator accepts the catalog; F03/F16 remain. |
| Agent discovery | Scout, Profiler, Verifier, Matcher: real; Coach: stub | Confirms F01 in the actual loaded graph. |
| Real graph: Student A | 20 candidates, 16 verified, four rejected, 16 matches, eight marked eligible; both loops once | Finishes, but the final three-item plan contains stub rationale/tasks/tips. |
| Real graph: strong sample | 19 candidates, two verified, 17 rejected; two marked eligible | Finishes with stub planning; most candidates are lost to the URL bug. |
| Real graph: weak sample | 20 candidates, 12 verified, eight rejected; six marked eligible | Finishes with stub planning; missing information is admitted as eligibility. |
| Profiler exception | Error logged, eight matches still eligible, three-item stub plan | Demonstrates misleading success after a core input-stage failure. |
| Malformed agent return | Guard raises `AttributeError` | Confirms F15 beyond source inspection. |
| UI initial load / empty input | No Streamlit exceptions; empty submission produces the intended warning | Basic entry behavior works. |
| UI normal run | No Streamlit exceptions; three ranked entries and one stub checkbox | Rendering works, substantive planning remains incomplete. |
| UI replay | No Streamlit exceptions; shipped stub plan displayed | Playback works but is not a trustworthy real-agent demonstration. |
| Replay other filename | Button enabled, click does nothing | Confirms F11. |
| Changed checklist task | New task remains checked | Confirms F18. |
| Cache-save exception | Final result exists; log says `Run failed: synthetic disk failure` | Analysis and persistence failure are conflated. |

Graph probes set `llm.PROVIDERS = []` to force deterministic local fallback. Streamlit checks used `streamlit.testing.v1.AppTest`; socket connections and cache saves were mocked. The shipped recording was preserved. One scenario deliberately made the save mock raise to check error handling. No paid model calls, application submissions, source-page revalidation, or changes to application behavior were performed.

These checks establish local Python/Streamlit runtime behavior. Browser visual layout, mobile usability, live-provider performance and deployment behavior were not assessed.

Repeat the baseline checks in PowerShell from this repository:

```powershell
$auditPython = Join-Path $env:LOCALAPPDATA 'Codex\venvs\futurist-audit\Scripts\python.exe'
& $auditPython -m pytest -q -ra
& $auditPython -m scripts.validate_data
& $auditPython -m pip check
```

To inspect the current UI with the prepared environment:

```powershell
& $auditPython -m streamlit run app.py
```

Only this audit document has been added to the working tree. No implementation fixes, commits, or pushes have been made.

## 7. Remediation on `ali-haider`

The sections above preserve the original baseline. Implementation work followed on 7 November 2026, including integration of the team's newer Coach contribution from `origin/main` before extending it.

| Finding | Remediation | Verification |
| --- | --- | --- |
| F01 | Five real agents; unavailable/broken modules report failures. Coach now schedules within capacity and explicitly defers infeasible work. | Real-agent smoke tests, Coach tests and failed-Profiler regression. |
| F02 | Parsed, normalized host checks replace substring URL classification. | Devpost/Microsoft, uppercase shortener, irrelevant-path and unsafe-scheme regressions. |
| F03 | Shared typed record validation and individual rejection isolate malformed records. Description scam claims are included in the checks. | Parameterized malformed-record tests retain a valid peer. |
| F04 | Scout records local-reread evidence; stale/imminent records retain review warnings after the bounded feedback loop. | Stale second-pass regression and real graph loop tests. |
| F05 | Verifier uses deterministic checks only. A model cannot approve/reject listing legitimacy. | Regression rejects any attempted model call during verification. |
| F06 | Labelled profiles and prose retain field boundaries; guided entry and visible parsed details support corrections. | Section parsing, model-grounding and guided-input tests. |
| F07 | Eligibility has eligible/conditional/ineligible states. Missing evidence cannot become confirmed eligibility; failed parsing creates no application plan. | Unknown-rule and failed-Profiler real-flow tests. |
| F08 | Explicit skill normalization replaces substring matching; field/nationality aliases are also normalized. | Java/JavaScript, C/C++, React/React Native and alias tests. |
| F09 | Obsolete smoke imports/skips removed. Actual agent graph and Streamlit flows are covered. | Full suite completes without skipped tests. |
| F10 | New UI exposes source links, fit reasons, eligibility conditions, skill resources, weekly capacity, profile correction and exports. | Streamlit user-flow tests. |
| F11 | Real-agent synthetic walkthrough replaces the old recording; replay uses an actual current-session journal or explicit demo. `REPLAY_MODE` is connected. | Validated offline replay and UI replay tests. |
| F12 | Profiler uses the shared optional `ask` API. Groq primary/fallback and configured Ollama use the declared settings; models cannot replace the deterministic schedule. | Grounding, provider-fallback and immutable-schedule tests. Live providers were not called. |
| F13 | Connectivity probing removed. Local analysis/replay do not call providers or skip structural URL checks. | Streamlit tests make external access fail; offline host checks still apply. |
| F14 | Session-scoped recordings, restricted names, schema validation and atomic writes. Save failure preserves completed results. | Namespace isolation, path traversal, corruption, atomic-save and save-error tests. |
| F15 | Guard validates returned mappings, owned shapes, messages, profiles, matches and plans; it supplies copied input and records failures. | Bad-return and nested-input-mutation regressions. |
| F16 | Scout deduplicates source identities. Full eligibility is explicitly marked incomplete for unplanted records; undocumented skills get neutral scoring. | Deduplication and uncertainty tests. **Official program facts still require independent review.** |
| F17 | Complete synthetic profiles, rewritten README, pinned direct dependencies/full lock, and Windows/Ubuntu CI workflow. | Strong profile scores 97, Student A 53, starter profile 9; locked installation and tests. |
| F18 | Task keys include the current plan identity and task text. | Streamlit test preserves checks in one plan and resets them for a new analysis. |

### UX changes and activity semantics

The new responsive interface uses warm white, solid forest/sage surfaces and local SVG icons. It has no gradients, emojis, decorative divider lines, progress bars or status dots. Large agent cards show actual start/completion/failure events. Directed messages expose Scout/Verifier and Matcher/Coach handoffs, including feedback rounds. The optional step-by-step view walks through real events; when analysis has finished, it explicitly says the view is a walkthrough and offers immediate access to results.

Profile edits survive activity-control reruns. Normal work, replay, conditional matches, no-match cases, exports and checklist state are exercised with Streamlit AppTest. The original shared `cache/last_run.json` was replaced with `cache/demo.json`; private recordings are ignored by Git and scoped to a random browser session.

### Remaining boundaries

- The catalog's dates, fees, program descriptions and full eligibility have not been freshly verified against official sources. The application makes that limit visible and provides source links. Live discovery and applications are outside this version.
- Session isolation is not authenticated multi-user storage. Raw local profile recordings remain on the machine until their owner removes them; no account or recovery system is claimed.
- The browser/computer-use bridge was unavailable. Desktop/mobile screenshots and browser visual QA could not be performed. Responsive CSS, Streamlit runtime interactions and HTTP health were checked; those checks do not substitute for visual review.
- Optional provider code is covered by deterministic mocks; no paid/live model request was made.

### Final local validation

The project-local `.venv` was created from the universal `requirements.lock` with Python 3.12.14. The full suite passed: **160 tests, zero skips** (50.54 seconds in the clean environment). Dependency checking reported **68 compatible installed packages**. The dataset validator reported **42 records, zero errors and 41 warnings**: 40 incomplete-eligibility notices and one duplicate-source notice. The synthetic real-agent demo contains 28 events and no agent failures. Local Streamlit HTTP health returned `200`.
