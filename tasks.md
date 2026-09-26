# Job Search Agent — Build Plan

Sequenced task list for building this step by step. Check items off (`- [ ]` → `- [x]`) as we
complete them. Each phase should end with something you can actually run and see working before
moving to the next one.

Built with the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python) (Python),
following the agent-team pattern from the course referenced in `docs/brief.md`
(one specialist agent per job, a coordinator wiring them together, a validation/refinement loop).
Storage is local (SQLite), no external services beyond the job-source APIs/feeds, Claude's web
search tool, and the Anthropic API.

## Architecture at a glance

```
                 +--> config-driven RSS feeds ----+
sources          +--> Adzuna API -----------------+--> normalize+dedupe (SQLite) -> rule-based
                 +--> general web search (jobs) --+        pre-filter
                                                              |
                                                              v
                                           fit agent (Haiku coarse pass)
                                                              |
                                                              v
                                       fit agent (Sonnet detailed pass on survivors)
                                                              |
                                                              v
                 general web search (companies) --> "why follow" agent --+
                                                                          v
                                          local web dashboard (jobs + companies to watch)
                                                                          |
                                                                          v
                                    feedback buttons (relevant / not relevant) on the dashboard
                                                                          |
                                                                          v
                                          feedback store -> feeds back into agent prompts
```

Everything left of the LLM steps is plain Python and free to run as often as you like. The LLM
only sees listings that survive the cheap filters, and only the cheaper model sees the full
volume — the expensive model only sees what's already promising.

The **general web search** paths (for jobs, and separately for companies) exist specifically so
the system isn't limited to boards/APIs you thought to configure — see Phase 3 and Phase 16.

---

## Phase 0 — Project setup

- [x] Create Python project skeleton (`pyproject.toml` or `requirements.txt`, `src/` layout)
- [x] Set up virtualenv, install `claude-agent-sdk`
- [x] Get an Anthropic API key, set spend cap in Console, store key via `.env` (gitignored)
- [x] Confirm setup with a minimal "hello agent" script that makes one Claude call and prints cost

## Phase 1 — Your profile (CV + preferences)

- [x] Decide the profile format (e.g. a `profile/` folder: `cv.md` + `criteria.yaml`)
- [x] Define `criteria.yaml` fields: target roles, locations, salary band, must-haves,
      dealbreakers, keywords to boost/avoid
- [x] Write a loader that reads CV + criteria into a single structured object/string the agents
      can use as context
- [x] Sanity check: print the loaded profile back out correctly

## Phase 2 — First source agent (THE unijobs RSS)

> Originally planned around jobs.ac.uk, but they no longer publish a public RSS feed (checked
> 2026-09-25 — no autodiscovery link, no working feed URL pattern; they've moved to an
> email-only "Job Alerts" account feature instead). Swapped to **THE (Times Higher Education)
> unijobs**, a comparable UK/international academic & research jobs board that does have a
> working RSS feed with keyword search:
> `https://www.timeshighereducation.com/unijobs/jobsrss/?keywords=<query>&countrycode=GB`
>
> Also checked NHS recruitment (jobs.nhs.uk, trac.jobs) for the same reason — neither has a
> public RSS feed either (jobs.nhs.uk: no feed anywhere on the site; trac.jobs: blocks
> non-browser requests outright). Not usable as a source this way.
>
> Now config-driven via `config/sources.yaml` — three feeds configured so far: `the_unijobs`,
> `nature_careers` (same underlying platform, also has a working feed), and
> `we_work_remotely_programming` (a different platform entirely, proving the config format
> generalizes).

- [x] Write a plain-Python fetcher for one THE unijobs RSS feed (no LLM involved yet)
- [x] Parse each entry into a common `Listing` shape: title, company, url, location, posted date,
      raw description, source
- [x] Print parsed listings to console to confirm parsing works
- [x] Design the `Listing` shape so other source agents (structured or search-based) can produce
      the same shape later
- [x] Generalize the fetcher into a config-driven generic RSS source (`config/sources.yaml`: name
      + feed URL + optional query params), so a non-programmer can add a new plain RSS board
      without writing code
- [x] Document a simple plugin interface (`fetch_listings() -> list[Listing]`) for anyone adding
      a bespoke API-based source (e.g. Adzuna, Phase 13) that can't be pure config

## Phase 3 — General web search source agent (jobs)

> Uses Claude's `WebSearch` tool with `permission_mode: "bypassPermissions"` (needed for
> unattended use — without it, tool calls hang waiting for interactive approval) and
> `output_format` (JSON schema) to get structured `Listing`-shaped results directly, rather than
> parsing free text. Costs real money per call unlike the RSS sources — one role search (a few
> WebSearch calls plus reasoning, on Haiku) ran $0.03–0.34 across different roles in testing —
> wide variance depending on how many searches a role needed. No spend guard yet; that's Phase
> 12, and this variance is exactly why it matters.

- [x] Add a search-based source agent using Claude's web search tool — the same pattern as the
      course's Day 1 search agent, applied to job hunting instead of research
- [x] Build natural-language search queries from `criteria.yaml` (roles, locations, keywords)
      rather than hardcoding query strings, so tuning it doesn't mean editing code
- [x] Prompt the agent to extract structured `Listing` fields from whatever it finds (title,
      company, url, location, description, source) — same shape as Phase 2's output
- [x] Run a handful of queries and compare what it surfaces against the RSS feed — the point is
      catching things the curated feeds/APIs would've missed (confirmed: direct company/ATS
      postings — Lever, Greenhouse — quite different in character from the academic RSS feeds)
- [x] Note: this can't reach LinkedIn directly (no scraping/login) — that stays covered by your
      own LinkedIn job alerts, outside this system

## Phase 4 — Storage, activity log & cost log

> Dedupe key is normalized (title, company), not URL — the same posting on two different boards
> has two different URLs, so matching on URL would miss exactly the cross-source duplicates this
> is meant to catch. Also added, beyond the original plan: an `events` table (activity log —
> "why was this recommended/filtered" will populate once Phase 5/6/7 exist) and a `cost_log`
> table (already used by `web_search.py`). `src/job_search_agent/ingest.py` is a small stand-in
> for the Phase 11 coordinator — runs both source agents once and stores everything.

- [x] Set up a local SQLite DB with a `listings` table (hash of title+company+url as dedupe key,
      status, first_seen, source)
- [x] Write insert-if-new logic so re-running any fetcher doesn't re-process old listings
- [x] Run the Phase 2 and Phase 3 fetchers into storage twice each, confirm reruns find zero new
      listings and overlapping postings from different sources correctly dedupe together
- [x] Add an `events` table logging pipeline activity (what ran, what it found)
- [x] Add a `cost_log` table logging LLM call cost per stage, wired into `web_search.py`
- [ ] Criteria-in-DB (so it's editable without a code/file change) deferred to Phase 8, when the
      dashboard gives an actual UI to edit it — see docs/brief.md follow-up decisions

## Phase 5 — Rule-based pre-filter

> Free-text matching turned out trickier than expected, worth remembering if this gets touched
> again (`src/job_search_agent/filters.py` has the full reasoning in comments):
> - **Location**: word-overlap matching against `criteria.locations`, with two lessons from real
>   data — short words (like "uk") need *exact* matching, not substring, or "uk" matches inside
>   "ukraine"; and a plain word-level synonym for "uk" like "united" also matches "United Arab
>   Emirates", so synonyms ("united kingdom", "artificial intelligence", etc.) are checked as
>   whole phrases instead.
> - **Role type**: checked against the listing *title* only, not the full description — RSS/API
>   descriptions are long, marketing-heavy text that incidentally mentions buzzwords ("AI",
>   "data", "product") regardless of the actual role, which made a full-text check pass almost
>   everything. Generic job-title words (engineer, developer, manager, ...) are also excluded
>   from matching, since they don't discriminate between "AI/ML Engineer" and "Mechanical
>   Engineer".
> - Verified end to end against 151 real fetched listings: 138 filtered, 13 kept, and spot
>   checks confirmed both directions — genuinely irrelevant roles (Account Manager, Shopify
>   Developer, Mechanical Engineer) correctly dropped, genuinely relevant ones (AI/research
>   roles in the UK) correctly kept.

- [x] Implement cheap, non-LLM filters using `criteria.yaml` (location, dealbreaker keywords,
      obviously-wrong role type)
- [x] Mark filtered-out listings in the DB with a reason, so nothing is silently dropped
- [x] Confirm on real data that obviously irrelevant postings get filtered before any LLM call
      would happen

## Phase 6 — Fit agent v1 (coarse pass, Haiku)

> Built here as ordinary synchronous calls, one per listing, so it's easy to see what's
> happening. Phase 12 switches this and Phase 7 over to the Anthropic Message Batches API (50%
> cheaper, and nothing here needs an instant answer) once the synchronous version works.
>
> Verdicts go in a new `verdicts` table (listing_id, stage, verdict, reason), not a column on
> `listings` — keeps history if a listing is ever rescored, and each verdict also mirrors into
> the `events` activity log automatically (`db.log_verdict`). `listings.status` is updated to
> `haiku_yes`/`haiku_maybe`/`haiku_no` so Phase 7 can query for it directly.
>
> Tested against the 13 real listings that survived Phase 5: 1 yes, 8 maybe, 4 no, for $0.2423
> total (~$0.019/listing) — and the reasoning genuinely engaged with the CV/criteria context
> (referenced the thesis topic, years of experience, location preference specifically), not just
> generic keyword matching.

- [x] Build the first real fit agent: given one listing + your profile, ask Haiku for a coarse
      yes/no/maybe fit judgement with a one-line reason
- [x] Define the structured output contract (e.g. JSON: `{verdict, reason}`)
- [x] Run it over everything that survived Phase 5, store verdicts in the DB
- [x] Print the cost/turn count for the run

## Phase 7 — Fit agent v2 (detailed pass, Sonnet)

> Sonnet's prompt also includes Haiku's coarse verdict/reason (via a JOIN on `verdicts`), so it
> can focus on the specific uncertainty already flagged rather than starting cold. Verdicts go
> in the same `verdicts` table as Haiku's (stage='sonnet'), `verdict` holds the numeric score,
> full structured payload (matched_criteria/concerns/rationale) goes in `detail_json`.
> `listings.status` becomes `sonnet_strong`/`sonnet_possible`/`sonnet_weak` (70/40 thresholds).
>
> Tested on the 9 real listings Haiku marked yes/maybe: $0.3752 total (~$0.042/listing, notably
> pricier than Haiku's ~$0.019). All scored 25-42 ("weak" to borderline "possible") - an honest
> result, not a bug: this batch is mostly UK academic Research Fellow/postdoc roles that
> generally require a PhD, which Sonnet correctly flagged as a likely hard mismatch that Haiku's
> one-line pass hadn't caught. Also caught a US-tax-residency exclusion and a veterinary vs.
> human healthcare mismatch buried in listing text. Cost comparison: scoring all 13 pre-filtered
> listings with Sonnet directly would have cost an estimated $0.542 - tiering saved ~$0.17 (31%)
> in this small batch, and that ratio improves a lot at real scale where Haiku screens out a much
> larger share as clear "no"s.

- [x] Take everything Haiku marked yes/maybe and send only those to Sonnet
- [x] Ask for a detailed structured verdict: fit score, matched criteria, concerns, short
      rationale
- [x] Store detailed verdicts in the DB alongside the coarse ones
- [x] Compare cost of running Sonnet on everything vs. only on Haiku's survivors

## Phase 8 — Results dashboard & onboarding

> Expanded after Phase 7 to also cover first-run setup, since the original plan (personal
> config files someone edits by hand) is a real barrier for anyone else picking this project up.
> Build order: the dashboard core first (there's already real scored data sitting in the DB from
> Phases 2-7 to view), then the onboarding wizard on top as the "nothing configured yet" entry
> point that leads into that same dashboard. Onboarding's schedule step only *captures* a
> preference (e.g. "run every 24h") — it doesn't set up a real scheduler; that's still Phase 17,
> a deliberate scope decision so this phase stays focused on the dashboard/onboarding UI itself.
> CV upload → `cv.md` is the trickiest part: it needs a real document-handling call (extract
> text from an uploaded PDF/DOCX, have Claude reformat it into markdown), not just a text prompt.

**Dashboard core:**

> `src/job_search_agent/webapp/` — Flask app factory (`__init__.py`), results view
> (`results.py` + `templates/results.html`, grouped by `sonnet_strong`/`possible`/`weak`, reading
> the `verdicts.detail_json` for score/matched_criteria/concerns), and criteria editing
> (`criteria.py` + `templates/criteria.html`, one-item-per-line textareas). Criteria now live in
> the DB (`db.get_criteria`/`save_criteria`), seeded once from `profile/criteria.yaml` via
> `profile.load_criteria()` — editing the YAML file after that point has no effect. Verified with
> a real server: results page correctly showed the 1 possible + 8 weak matches from Phase 7, and
> the criteria page round-tripped a save correctly (checked with curl, not just code review).
> Run with `uv run python -m job_search_agent.webapp`.

- [x] Add Flask, set up a minimal local web app that reads directly from the SQLite store (no
      separate report file)
- [x] Build a results page: matched listings grouped by score/verdict, with enough info to decide
      without opening the link (title, company, location, score, why, link)
- [x] Move criteria (roles, locations, salary, must-haves, dealbreakers, keywords) into a DB
      table, seeded once from `profile/criteria.yaml`, and add a simple editing page on the
      dashboard — this is what makes "dynamically updatable criteria" (raised after Phase 4)
      actually more convenient than editing the YAML file, so it's built here rather than earlier
- [x] Run the full pipeline end to end for the first time: fetch (RSS + search) → filter → score
      → view results in the dashboard

**Onboarding wizard (for a fresh clone with nothing configured yet):**

> `src/job_search_agent/webapp/onboarding.py` — a `before_request` hook on the whole app redirects
> to whichever step is first incomplete (checked fresh each request: env vars via `.env`, CV file
> existence, criteria in the DB), except requests already inside the onboarding blueprint itself.
> Deliberately **not a hard gate on the schedule step** — env/CV/criteria block the dashboard if
> missing, but a missing/skipped schedule preference doesn't, since nothing else depends on it
> (confirmed this mattered: an early version gated on it too, which would have bounced the
> already-configured real setup back into onboarding on every page load).
>
> CV upload (step 2) does real document handling: `src/job_search_agent/cv_import.py` extracts
> text locally (`pypdf`/`python-docx`, free) then has Sonnet reformat it into Markdown (one paid
> call, logged to `cost_log` under `onboarding:cv_import`) — doesn't work on scanned/image-only
> PDFs (no OCR), and says so rather than producing garbage. Step 3 reuses the same
> `_criteria_fields.html` partial and `criteria_dict_from_form()` as the standalone Criteria page,
> so the two forms can't drift out of sync. `.env` writes go through
> `job_search_agent.env_utils.set_env_var()`, which updates the *running* process's environment
> as well as the file, so a key set mid-session takes effect immediately without a restart.
>
> Tested live end to end against a real running server (not just code review): confirmed an
> already-configured user is never gated; confirmed the redirect fires correctly when `cv.md` is
> (temporarily) missing; posted real values to all four steps, including a real file upload that
> went through actual text extraction + a real Sonnet call and produced a correct `cv.md`. All
> tests that touched real files (`.env`, `profile/cv.md`) backed them up first and restored the
> originals afterward.

- [x] Detect first-run (no `.env` / no criteria in the DB) and redirect to the onboarding flow
      instead of the dashboard
- [x] Step 1 — collect `ANTHROPIC_API_KEY` and `CONTACT_EMAIL`, write to `.env`
- [x] Step 2 — accept a CV upload (PDF/DOCX/text), use Claude to extract and reformat it into
      `profile/cv.md`
- [x] Step 3 — collect criteria (roles, locations, salary, must-haves, dealbreakers, keywords)
      via a form, save into the criteria DB table from the dashboard-core tasks above
- [x] Step 4 — capture a run-frequency preference (store only — Phase 17 is what would act on it)
- [x] On completion, redirect into the normal results dashboard

> **Follow-up cleanup (2026-09-26, prompted by real use during Phase 13):** `profile/criteria.yaml`
> and its tracked template `profile/criteria.example.yaml` were removed. Both were originally the
> file-based bootstrap path this section superseded once the onboarding wizard existed - Step 3's
> GET handler already caught `load_criteria()`'s `FileNotFoundError` and fell back to an empty
> `Criteria()` for the form, so the example was never actually load-bearing for a dashboard-first
> setup, and the personal `criteria.yaml` had already drifted from the DB (a role added later via
> the dashboard was never reflected back into the file). `profile.load_criteria()` still seeds the
> DB from a hand-written `profile/criteria.yaml` if one exists, for anyone who prefers running the
> pipeline scripts directly over the dashboard, but no longer requires one - its `FileNotFoundError`
> now points at the onboarding wizard instead of a template file that no longer exists.
> `profile/cv.example.md` was deliberately left alone - CV upload isn't gated the same way (Step 2
> does real extraction, but a user editing `cv.md` by hand instead still needs to know its format).

## Phase 9 — User feedback capture

> Added a `feedback` column to `listings` (TEXT, `relevant`/`not_relevant`/NULL) via a real
> migration (`db._add_column_if_missing`) rather than dropping the dev DB like earlier phases —
> it now holds real scored data worth real API spend, not disposable test fetches. Each change
> also writes to the `events` activity log (`db.set_feedback`), so the full history of what you
> marked and when survives even though the `listings` column itself only holds current state.
> Buttons show which state is currently selected (disabled + relabeled) and let you switch your
> mind by clicking the other one. Tested live end to end: POSTed feedback, confirmed it persisted
> in the DB and rendered correctly (disabled/relabeled button) on a fresh page load, switched it,
> confirmed both changes were logged as separate events.

- [x] Add relevant/not-relevant buttons on the dashboard for each listing, writing feedback
      straight to the SQLite store
- [x] Confirm feedback persists across runs and page reloads

> **Follow-up fixes from real usage (2026-09-25):** trying this against actual live listings
> surfaced three gaps, fixed the same day:
> - **Free-text notes.** Added a `feedback_note` column and a text input alongside the buttons
>   (same `<form>`, submitted together via named submit buttons) - `db.set_feedback()` now takes
>   an optional note, included in the activity-log message too.
> - **Marking "not relevant" jumped to the top of the page.** Rather than fixing scroll position,
>   the real fix was structural: the site now has three separate views instead of one. `/` shows
>   only strong/possible matches minus anything rejected; `/excluded` shows what the *pipeline*
>   ruled out (filtered/Haiku-no/weak Sonnet score), grouped by stage; `/rejected` shows
>   everything *you've* marked not relevant, regardless of what the system thought. A listing
>   disappearing from the current list on feedback (rather than staying in place) makes the
>   scroll-jump problem moot instead of needing to solve it directly.
> - All three pages share one query helper (`webapp/results._fetch`) and one card partial
>   (`templates/_listing_card.html`), so feedback buttons/notes work identically everywhere and
>   can't drift out of sync between pages.
> - Verified live, including a real accidental discovery: while testing, real usage had already
>   marked 5 of the original 8 weak-Sonnet listings not relevant, leaving 3 - confirming the
>   whole flow (button click → DB write → page relocation) was already working under real load,
>   not just the scripted test.
>
> **Two more real bugs, found by the user clicking real listings right after the above shipped:**
> - **Stats didn't sum to the total** (151 total, but 150 excluded + 5 rejected = 155). Cause: the
>   "excluded" count and the `/excluded` page used different WHERE clauses - the stat counted
>   every system-excluded listing regardless of feedback, while the page (correctly) excluded
>   ones you'd also marked not relevant, so the overlap got double-counted. Fixed by making every
>   listing fall into exactly one of four buckets (rejected / main / excluded / pending, feedback
>   checked before status) via shared `MAIN_WHERE`/`EXCLUDED_WHERE`/`REJECTED_WHERE`/
>   `PENDING_WHERE` constants in `webapp/results.py`, used by both the pages and the stats query -
>   they literally cannot drift apart now, by construction.
> - **Marking an excluded listing "relevant" didn't move it anywhere.** The main page's query
>   only ever looked at `status IN ('sonnet_strong', 'sonnet_possible')` - a listing whose status
>   was still `filtered`/`haiku_no`/`sonnet_weak` (feedback doesn't change status) never matched,
>   so it just silently disappeared from view. Fixed: the main page now also shows anything with
>   `feedback = 'relevant'` regardless of status, under a new "Your picks (marked relevant)"
>   section (`_group()`'s `fallback_label` parameter) so an override is visible rather than
>   vanishing.
> - Both confirmed against real listings the user had actually clicked, not synthetic test data.
>
> **Third round — scalability and clarity, from continued real use:**
> - **Was it clear when a note was actually saved?** No — the note field shared a form with the
>   relevant/not-relevant buttons, so typing one did nothing until a button was clicked, and once
>   a listing was marked, its matching button became disabled, making the note un-editable
>   afterwards without switching feedback back and forth. Fixed: a distinct "Save note" button
>   (`db.set_note()`, updates the note without touching feedback) plus a "Saved" confirmation that
>   appears next to the specific listing just acted on, via a `?saved=<id>` redirect parameter
>   built from a `next` hidden field on every form (not `request.referrer`, which isn't reliable).
> - **Long lists won't scale as cards.** `/excluded`, `/rejected`, and the new `/hidden` now
>   render as compact `<details>`-based rows (title/company/location/tag/score in the closed
>   `<summary>`, full rationale/matched/concerns/reason in the expanded body) - no JS needed,
>   native HTML disclosure. Paginated at 25/page via `_fetch()`'s `page` parameter, driven by
>   plain `?page=N` links. The main results page stays full-card and unpaginated, deliberately -
>   it's meant to stay small (only strong/possible + your own overrides).
> - **A "remove from the dashboard entirely" status**, independent of relevant/not-relevant
>   opinion: a new `hidden_at` column (`db.set_hidden()`), with `HIDDEN_WHERE` taking priority
>   over every other bucket in the partition. Listings stay in the DB (so dedupe still works) but
>   don't appear anywhere else. A `/hidden` page with an "Unhide" toggle exists as a safety net -
>   not explicitly requested, but added since a genuinely irreversible destructive action from a
>   single click would be a worse default.
> - All three fixes tested live end to end (note-only save leaves feedback untouched; hide moves
>   a listing to `/hidden` and back; pagination shows distinct, correctly-tagged content per page;
>   the 5-way stats partition - shown/excluded/rejected/hidden/pending - still sums to the total).
>
> **Fourth round — reducing clicks, from continued real use:**
> - **Hide took three clicks** (expand row → find Hide inside the detail panel → confirm
>   dialog) for something meant to be quick and is trivially reversible via the Hidden page. Fixed:
>   Hide/Unhide moved out of the detail panel into a new shared `_hide_button.html`, included
>   directly in the row header (table pages) and the card header (main page) — always visible,
>   no expand needed. The `confirm()` dialog was removed entirely; reversibility (Unhide) does the
>   job a confirmation would have.
> - **Expand/collapse wasn't discoverable** — it used a native `<details>/<summary>` element where
>   the *entire* row toggled on click except the title link, which wasn't obvious (nothing else
>   in a row looks clickable, and clicking near-but-not-on the title did something unexpected).
>   Replaced with a plain row + an explicit "Show details"/"Hide details" button
>   (`toggleDetails()`, a small vanilla-JS function in `base.html` - the only real JS in the
>   project, everything else is plain forms) - clicking anywhere else in the row now does nothing.
>   The row a save/hide action just touched auto-expands on redirect (via the same `saved_id`
>   already used for the "Saved" indicator) so the confirmation is visible immediately rather than
>   landing inside a collapsed panel.
> - Verified live: single-click hide with no dialog, confirmed row auto-expands with "Saved" and
>   "Hide details" shown after a same-page note save, confirmed the Hide button appears correctly
>   on both the table rows and the main page's cards.

## Phase 10 — Learning from feedback

- [x] Pull accumulated feedback into the fit-agent prompt as examples ("here are jobs I said
      yes/no to before, and why, if known")
- [x] Re-run the fit agent on a fresh batch and check whether verdicts noticeably reflect past
      feedback
- [x] Decide how much feedback history to include (recency/cap) to keep prompt size sane

> `db.get_feedback_examples()` pulls the most recent listings the user gave relevant/not_relevant
> feedback on (ordered by the feedback *event* itself, not a later note-only edit, so touching up
> a note doesn't bump a listing back to "most recent"), capped at `FEEDBACK_EXAMPLES_LIMIT = 20` in
> `profile.py` — a flat cap rather than a time window, since usage is still light and a count is
> simpler to reason about; revisit if feedback volume grows enough that 20 stops being "the recent
> stuff." `profile.feedback_examples_context()` renders them as a `## Feedback from past listings`
> block (verdict + title/company + the user's own note when given), inserted into both
> `fit/haiku.build_prompt()` and `fit/sonnet.build_prompt()` right after the CV/criteria block, and
> fetched once per run (not once per listing) since it doesn't change mid-run. Returns `""` when
> there's no feedback yet, so early runs are unaffected.
>
> Verified live on a fresh batch (27 new listings fetched via `ingest.py`, 16 survived the
> pre-filter): Haiku's one 'no' verdict explicitly cited it — *"Research Fellow role requiring PhD
> (which Alex explicitly rejected before)"* — matching several real not-relevant marks on
> PhD-gated research-fellow roles. Sonnet showed the same effect on a different listing: *"a
> dedicated AI/ML engineering title rather than a research-fellow/PhD-gated role (which past
> feedback shows the candidate correctly rules out)."* Both stages are demonstrably weighing past
> feedback, not just the static CV/criteria block, without it dominating the scoring (both listings
> were still judged on their own merits alongside the feedback-derived pattern).
>
> Also hit, unrelated to the feedback-context change itself: one Sonnet call failed with "Reached
> maximum number of turns (1)" mid-run — re-running the same listing standalone immediately after
> succeeded, so this looks like transient API/SDK flakiness rather than a real bug. Worth noting:
> `run_sonnet_pass()`/`run_haiku_pass()` only commit once, at the very end of the `with db.connect()`
> block, so a crash partway through a run (like this one) loses every already-scored listing's
> result in that run, not just the one that failed - nothing was corrupted, just re-run needed. Not
> fixed now (out of scope for this phase and hasn't caused a real problem yet, since a re-run is
> cheap and safe), but worth an incremental-commit fix if larger batches make a partial loss costly.

## Phase 11 — Coordinator agent

- [x] Build a coordinator that runs the whole pipeline (sources → filter → Haiku → Sonnet →
      report) as one orchestrated flow, matching the course's coordinator pattern
- [x] Add per-agent turn caps so a bad run can't loop indefinitely
- [x] Add basic logging of what the coordinator did at each stage

> `src/job_search_agent/coordinator.py` (`uv run python -m job_search_agent.coordinator
> [keywords] [--no-web-search]`) runs RSS fetch → web search → pre-filter → Haiku → Sonnet in one
> call, superseding running `ingest.py`/`filters.py`/`fit/haiku.py`/`fit/sonnet.py` by hand
> (`ingest.py` itself is unchanged — the coordinator calls its `ingest_rss`/`ingest_web_search`
> functions directly rather than duplicating them). `--no-web-search` skips the one costly step
> for a free/cheap RSS-only run, since web search re-runs cost real money every time (no spend
> guard yet — that's Phase 12).
>
> Turn caps per agent already existed before this phase (`max_turns=1` on Haiku/Sonnet's
> single-call structured output, `max_turns=6` on web search's multi-step tool use) — what this
> phase actually added was the *retry* half of "turn/retry cap per agent" from the course pattern:
> `claude_client.call_with_retry()` (2 attempts, catches `ClaudeSDKError`) now wraps each
> per-listing Haiku/Sonnet call, motivated directly by the transient "Reached maximum number of
> turns" error hit during Phase 10 testing. A listing that still fails after retrying logs the
> failure to `events` and is skipped (left in its prior status, so it's picked up again next run)
> rather than crashing the whole batch. Also fixed the incremental-commit gap noted in Phase 10:
> `run_haiku_pass`/`run_sonnet_pass` now `conn.commit()` after every listing, not just once at the
> end, so a mid-run failure no longer loses already-scored results.
>
> Coordinator-level logging goes to the `events` table (`stage='coordinator'`) at the start/end of
> each stage plus a final total-cost line — visible on the dashboard's new **History** page
> (`/history`, `src/job_search_agent/webapp/history.py`), added because the user asked for one
> directly: a paginated, newest-first list of every `cost_log` entry (timestamp, stage, model,
> turns, cost) with a per-stage cost breakdown at the top. Verified live: ran the coordinator with
> `--no-web-search` (free RSS fetch + pre-filter, 0 listings survived so Haiku/Sonnet correctly did
> nothing), confirmed the `events` log recorded each stage in order, and confirmed `/history`
> renders real accumulated data (57 calls, $2.39 total, 3 pages) correctly including the cost
> breakdown table and pagination. `call_with_retry` unit-tested directly (recovers on a transient
> failure, raises after exhausting both attempts).

## Phase 12 — Cost controls & observability

- [x] Switch the Phase 6/7 fit-agent calls to the Anthropic Message Batches API (submit a batch,
      poll for completion, retrieve results) instead of one-by-one synchronous calls — 50%
      cheaper for the same requests, using the plain `anthropic` Python SDK rather than
      `claude-agent-sdk` (which is built for synchronous tool-use loops, not batch submission)
- [x] Add prompt caching for the profile/criteria block (identical across every fit-agent call in
      a run)
- [x] Track and print total run cost (calls, tokens, $ estimate) at the end of every run
- [x] Add a configurable max-listings-per-run / max-spend-per-run guard — this matters more once
      Phase 3's open-ended search queries are in the mix

> `fit/haiku.py` and `fit/sonnet.py` no longer make one `claude-agent-sdk` `query()` call per
> listing - each run builds one Batches API request per listing (`fit/batch_client.py`, using the
> plain `anthropic` SDK's `AsyncAnthropic`) and submits them all as a single batch, polling
> (`POLL_INTERVAL_SECONDS = 10`, capped at `MAX_POLL_SECONDS = 1800`) until every request has a
> result. A request that errors, cancels, or expires is logged and skipped (left in its prior
> status so the next run picks it up) rather than failing the whole batch.
>
> The CV/criteria/feedback-examples block - identical for every listing in a run - moved out of
> the per-listing prompt string and into the `system` parameter with a `cache_control: ephemeral`
> breakpoint, so Anthropic can cache and reuse it instead of reprocessing it per request.
> `pricing.py` prices raw token counts ourselves (`PRICES` per model, `BATCH_DISCOUNT = 0.5`),
> since the Batches API - unlike `claude-agent-sdk`'s `ResultMessage.total_cost_usd` - only
> returns token counts, not a dollar figure; `cost_log` gained `input_tokens`/`output_tokens`
> columns (migration, not a drop) so the dashboard's History page can show real token counts, not
> just an estimated cost.
>
> `limits.py` adds the volume/spend guard: `MAX_LISTINGS_PER_RUN` (default 50, `.env`-configurable)
> caps how many listings a single batch takes on, deferring the rest to next run; `check_spend_cap`
> estimates a batch's worst-case cost (every request hitting its full `max_tokens`, no caching
> credit - deliberately pessimistic since it's a safety net, not a forecast) before submitting, and
> raises rather than submits if it exceeds `MAX_SPEND_PER_RUN_USD` (default $2.00). This sits
> underneath the Anthropic Console spend cap `docs/brief.md` already recommends setting directly
> on the account - a second, app-level line of defense, not a replacement for it.
>
> Two raw-API schema gaps surfaced only by a real batch call, not by code review - `claude-agent-sdk`'s
> `output_format` had evidently been tolerating both: (1) `output_config.format.schema` requires
> `additionalProperties: false` explicitly on every object type, or every request in the batch
> errors; (2) integer properties don't support `minimum`/`maximum` at all - removed from
> `ASSESSMENT_SCHEMA`'s `score` field, replaced with a defensive `max(0, min(100, ...))` clamp
> after parsing, since the prompt still asks for 0-100 but the schema can no longer enforce it.
>
> Verified live end-to-end on two real listings (temporarily reset from `filtered` to `pending_fit`
> for the test, restored afterward): Haiku batch scored both correctly (still citing past feedback
> in its reasoning - the Phase 10 loop survived the rewrite intact), one was bumped to
> `haiku_maybe` to test the Sonnet batch too, which also scored correctly. Confirmed caching
> behaviour empirically rather than assuming it: Sonnet's system prompt (~3.3k tokens) triggered a
> real `cache_creation_input_tokens` write, but Haiku's (~1.9-2.4k tokens) didn't cache at all -
> Haiku-tier models need a 2048-token minimum to cache at all, Sonnet-tier only needs 1024, and
> this project's profile/criteria/feedback block happens to sit between those two thresholds. Not
> a bug, just a real limit worth knowing: caching may or may not engage on Haiku calls depending on
> how long the user's own CV/criteria/feedback history is.
>
> Also, since this phase moved Haiku/Sonnet off `claude-agent-sdk` entirely, `claude_client.call_with_retry`
> (added in Phase 11 for exactly this class of call) would have had no remaining caller - wired it
> into `sources/web_search.py`'s `search_for_role` instead, the one other place a single flaky
> `claude-agent-sdk` call could still take down a whole run.

## Phase 13 — Second structured source agent (Adzuna API)

> `src/job_search_agent/sources/adzuna.py` is the first bespoke (non-RSS) source module,
> implementing the `fetch_listings(...) -> list[Listing]` plugin interface documented in
> `sources/__init__.py` for real: an authenticated JSON API rather than something `feedparser`
> already understands. `fetch_all()` loops over `criteria.roles` and does one search per role
> (same pattern as `web_search.search_all`), defaulting to `country="gb"` (matching the existing
> RSS feeds' hardcoded `countrycode: GB`, not worth generalizing yet). No `cost_log` entries -
> Adzuna's free tier isn't priced in Claude tokens, so unlike `web_search.py` there's nothing to
> record.
>
> **Adzuna credentials are optional, unlike `ANTHROPIC_API_KEY`/`CONTACT_EMAIL`** - a deliberate
> difference from those two. This is an *added* source on top of an already-working pipeline, not
> a new hard requirement for every user; `ingest.ingest_adzuna` checks `adzuna.have_credentials()`
> first and skips with a logged event + console message if unset, rather than crashing the whole
> coordinator run the way `require_credentials()` (used only when running the module directly)
> would. Verified live: running with `ADZUNA_APP_ID`/`ADZUNA_APP_KEY` deliberately unset skips
> cleanly with `Adzuna: skipped (no API credentials set in .env).` and a matching `events` row,
> nothing else in the run affected.
>
> Verified live end to end with real credentials: fetched 20 real UK listings for a single role
> (`AI/ML Engineer` - Sainsbury's, BAE Systems, Siemens, etc., all with working `redirect_url`
> links), then 37 across all four configured roles via `ingest.ingest_adzuna`, of which 34 were
> new and 3 were skipped as duplicates - confirmed (by recomputing dedupe keys against a fresh
> fetch) those 3 were the *same job* surfacing under two different role searches (e.g. a
> Sainsbury's "AI/ML Engineer" posting matched by both the `AI/ML Engineer` and `Research/Data
> Science` searches), not a bug - direct proof the source-blind `UNIQUE` dedupe constraint works
> on Adzuna's own overlapping results, via the exact same code path a cross-source collision would
> hit. A second `ingest_adzuna` run against the same DB found 0 new (idempotent, matching the
> Phase 4 rerun check). No genuine overlap turned up between Adzuna and the RSS/web-search sources
> in this data - expected, not a gap: Adzuna's UK corporate-recruiter listings and the academic RSS
> feeds/curated web-search results are just different postings in practice, but the mechanism
> itself (a single `dedupe_key` computed the same way regardless of `source`) is what's being
> proven, and it needed no Adzuna-specific code to work.
>
> Confirmed zero downstream changes needed: ran `filters.run_filters()` immediately after the
> Adzuna ingest with no code changes, and it processed the new `adzuna`-sourced rows exactly like
> any other source, using the same rule-based logic as RSS/search listings with no special-casing.
> Wired into both `ingest.py` (`ingest_adzuna`, run alongside `ingest_rss` in `main()`) and
> `coordinator.py` (called right after `ingest_rss`, before the costlier web search step) - the
> coordinator's Haiku/Sonnet passes will pick up the surviving Adzuna listings on the next run
> without any change to those stages either.
>
> **Follow-up bug, found immediately from real usage:** the first live run filtered 18 of 34
> Adzuna listings, most on location - e.g. "Belfast, Northern Ireland" and "Woking, Surrey" were
> rejected as not matching "UK-wide (open to relocation)" in criteria, which looked at first like
> a criteria-data problem but wasn't: `filters.py`'s location check is plain word-overlap, and
> `"uk"` was already present in the criteria's word set - the actual bug was on the *listing*
> side. `_to_listing()` only used Adzuna's `location.display_name` (e.g. "Belfast, Northern
> Ireland"), which never mentions the country, while Adzuna's own `location.area` field is a
> broad-to-narrow hierarchy (`["UK", "Northern Ireland", "Belfast"]`) that does. Fixed with a
> `_location_text()` helper that appends `area[0]` (the country) to `display_name` when it isn't
> already present, so "UK-wide" can match on the word "uk" the way it's meant to. Also confirmed,
> while diagnosing this, that criteria.yaml has no effect once the DB is seeded (Phase 8) - the
> live criteria (fetched via `db.get_criteria`) had already diverged from the file (missing a
> fourth role added to the DB later via the dashboard), so any fix here had to be a code fix, not
> a criteria edit, which wouldn't have touched the actual bug anyway.
>
> Verified live: deleted the 34 test-only Adzuna rows inserted during initial verification (none
> had feedback/hidden state set), re-ran `ingest_adzuna` + `run_filters()` with the fix in place -
> Belfast and both Woking listings now correctly survive to `pending_fit`, and location dropped
> out of the filter reasons entirely (10 filtered, all now for legitimate reasons - "Full Stack
> Developer"/"Backend Engineer"-type titles with no role/keyword overlap, one "banking" dealbreaker
> - 24 kept for scoring, up from 16 before the fix).

- [x] Implement an Adzuna API fetcher producing the same `Listing` shape from Phase 2
- [x] Plug it into the existing pipeline with no changes needed downstream — proves the
      pluggable-source design actually works
- [x] Confirm dedupe correctly merges overlapping postings across all sources (RSS, search,
      Adzuna)

## Phase 14 — Validation/retry loop for uncertain calls

> No such thing as "uncertain" existed before this phase - Sonnet always returned a confident-
> looking 0-100 score with no way to distinguish "well-informed judgement" from "best guess off a
> thin teaser description". Added an `uncertain` boolean to `ASSESSMENT_SCHEMA`/`Assessment`
> (`fit/sonnet.py`), prompted explicitly: still give a best-guess score either way, but flag
> honestly when the description didn't give enough to judge properly. A listing Sonnet marks
> uncertain gets an intermediate `sonnet_uncertain` status instead of a normal
> strong/possible/weak bucket, picked up by the new `fit/retry.py`.
>
> `fit/retry.py` fetches the full posting page (`requests` + `BeautifulSoup` - new dependency,
> strips script/style/nav/footer, capped at `MAX_PAGE_TEXT_CHARS = 6000`) and re-runs the same
> Sonnet assessment once with that fuller text appended to the original thin description. **Each
> listing is retried at most once, ever, by construction**: regardless of outcome (resolved, still
> uncertain even with the full page, or the page couldn't be fetched at all), status always moves
> out of `sonnet_uncertain` into a real bucket before the function returns for that listing, so
> next run's query for `sonnet_uncertain` rows won't find it again. The one exception, matching
> the existing Haiku/Sonnet convention: a *batch-level* failure (a transient API error, not a
> content judgement) leaves status unchanged so it's retried next run - that's not one of the
> listing's real chances being spent. A page that can't be fetched at all skips the Sonnet call
> entirely (no point paying for a re-assessment with no new information) and finalizes immediately
> from the original score, explicitly marked `uncertain: true, page_fetched: false` rather than
> silently looking identical to a confident verdict.
>
> Reuses `verdicts` the way its own Phase 6 design intended ("keeps history if a listing is ever
> rescored") - the retry writes a second `stage='sonnet'` row rather than a new stage name, so a
> listing's full history of re-assessment survives. This surfaced a real latent bug in
> `webapp/results.py`: `_fetch()`'s `LEFT JOIN verdicts sonnet ON ... stage = 'sonnet'` assumed
> exactly one row per listing, which a second row would have silently turned into a duplicated
> listing on every page. Fixed with a correlated subquery picking only the newest `sonnet` row.
> Also added `sonnet_uncertain` to `PENDING_WHERE` - without it, an uncertain listing with no
> feedback/hidden state would have fallen through every bucket in the five-way partition and gone
> uncounted, the exact bug class `webapp/results.py`'s own docstring already warns about from
> Phase 9. Wired into `coordinator.py` right after the Sonnet pass, using the same
> `MAX_LISTINGS_PER_RUN`/`MAX_SPEND_PER_RUN_USD` guards as Haiku/Sonnet (Phase 12), since a
> resolved retry is one more paid Sonnet call per listing. `_listing_detail.html` shows a one-line
> "Low confidence" note when `uncertain` is set, distinguishing "couldn't fetch the page" from
> "still thin even with the full page" - the only dashboard change this phase needed.
>
> **Verified with minimal real spend** (two isolated calls, ~$0.014 total, before touching any
> real pipeline data): a deliberately thin synthetic listing ("Great opportunity, apply now")
> correctly triggered `uncertain: true` with a sensible low score, confirming the widened
> `ASSESSMENT_SCHEMA` (a 5th field, still `additionalProperties: false`) is still accepted by the
> real Batches API - exactly the class of schema issue Phase 12's notes warn only surfaces as a
> real batch error. The same listing given a fuller fabricated description then correctly resolved
> to `uncertain: false` with a 95 score citing specifics (NHS, explainable AI, health tech) drawn
> straight from the candidate's real CV/criteria, confirming `build_retry_message` works.
>
> **Then one real end-to-end integration test against the live DB** (not just isolated scripts):
> temporarily marked a real, already-scored listing (`we_work_remotely_programming`, a genuine
> "Full-Stack Product Engineer" role) as `sonnet_uncertain` and ran `fit.retry` for real. It
> fetched the actual posting page, re-scored via a real batch call ($0.0165), and correctly
> revised the score from 25 to 8 after the fuller page revealed a US/Canada-only geo restriction
> invisible in the original thin RSS description - a genuinely more accurate verdict, not just a
> plumbing check. Confirmed the `verdicts` table held both rows (`sonnet` stage, scores 25 then 8),
> confirmed `results.py`'s fixed JOIN returned exactly one row for that listing (the latest, not a
> duplicate), and confirmed the five-way dashboard stats partition still summed exactly to the
> total listing count (227) before and after. Restored the listing to its exact pre-test state
> (deleted the test verdict/cost_log/event rows, reset status) afterward, since it was an
> artificial trigger for integration testing, not a genuine uncertain verdict from real usage.
>
> **A real limitation found along the way, not a bug**: Adzuna's own `redirect_url` links are
> behind anti-bot protection and return a 403 to any non-browser User-Agent (confirmed directly -
> a real Adzuna listing's link returned an "Access Denied" page). This means the retry mechanism
> will essentially always hit the "page unreachable" path for Adzuna-sourced listings specifically
> - handled correctly by design (graceful finalize, no wasted LLM call), just worth knowing:
> Adzuna listings that land as `sonnet_uncertain` will typically stay uncertain rather than get
> resolved, unlike RSS/web-search listings whose direct URLs fetch real page text successfully
> (verified against five real `the_unijobs` postings, 3.6-6k characters of real job-description
> text each).

- [x] For listings Sonnet marks "uncertain" (e.g. snippet too thin to judge), fetch the full job
      description page and re-run the fit check with fuller context
- [x] Cap retries so this can't spiral in cost
- [x] Confirm uncertain cases actually get resolved (or explicitly stay unresolved) rather than
      silently guessed at

## Phase 15 — Company/startup discovery agent

This is a different kind of output from a job listing: not "here's a role to apply for" but
"here's a company worth following, that might be worth a speculative application."

> **Deliberately kept out of `coordinator.py` entirely** - the user's own call, made explicitly
> for cost control: new companies/startups worth watching turn up far less often than new job
> postings, so this pipeline should eventually run on a separate, much less frequent schedule once
> Phase 17 wires up real scheduling. `companies.py` (top-level, sibling to `ingest.py`) is a fully
> standalone entry point (`uv run python -m job_search_agent.companies`) - nothing in the job
> pipeline calls it, and nothing here calls back into the job pipeline. Confirmed by grepping
> `coordinator.py` for any company-related reference: none.
>
> `company_lead.py` defines `CompanyLead` (name, sector, stage, why_relevant, careers_url, notes,
> source) as a genuinely separate shape from `Listing`, per the brief - no title/posted_date (not
> a role), a sector/stage instead.
>
> **Discovery and "why follow this" are one combined call, not two LLM stages.** The checklist
> below reads like it wants a separate lighter fit-agent step, but there's no volume/tiering
> problem to solve here the way there is for job listings (Haiku screening thousands down to what
> Sonnet needs to see) - a second call would just double the cost of an already-more-expensive,
> multi-turn search for no real benefit. `sources/company_discovery.py` reuses the exact WebSearch
> tool pattern from Phase 3's `web_search.py` (same `ClaudeAgentOptions`, `permission_mode=
> "bypassPermissions"`, Haiku, structured `output_format`), asking for `why_relevant` directly in
> the same structured-output schema as the discovery results themselves. Also reuses
> `web_search.SearchCost` rather than duplicating an identical dataclass.
>
> New `company_leads` table (`db.py`) with its own dedupe (normalized company name, not
> title+company - there's no second field to key on) and **3-valued feedback**
> (`relevant`/`not_relevant`/`already_known`) rather than listings' 2-valued column, per the
> phase's own wording - "I already know this one" is a genuinely different signal from "not
> relevant" (don't resurface vs. this suggestion was bad). `db.set_company_feedback`/
> `set_company_note` name the company directly in their `events` log message rather than adding a
> second nullable FK column to `events` (which is FK'd to `listings`) for one activity-log use.
>
> `webapp/companies.py` + `templates/companies.html`/`_company_card.html`: a single unpaginated
> page grouped by feedback state (To review / Marked relevant / Already known / Not relevant) -
> no need for the excluded/rejected/hidden multi-page treatment `webapp/results.py` needed, since
> this runs far less often and won't accumulate the same volume. Reused `results._redirect_with_
> saved` (generalized with a `default_endpoint` param) rather than duplicating the next-URL/saved-
> marker redirect logic. Registered without a Flask blueprint `url_prefix`, matching every other
> blueprint's convention of absolute route paths (`url_prefix` would have made `/companies`
> 308-redirect to `/companies/`, caught in live testing).
>
> `profile.company_feedback_examples_context()` mirrors Phase 10's `feedback_examples_context()`
> as a separate function (not a shared/parameterized one) since the feedback vocabularies and
> source tables genuinely differ. `companies.py`'s entry point fetches it once per run and passes
> it into the discovery prompt, same shape as the job pipeline's loop.
>
> **Verified live end to end, real spend $0.5862** (one multi-turn WebSearch run, in line with
> Phase 3's per-call cost range): found 10 real, well-targeted companies (Kheiron, Limbic AI,
> Accurx, Brainomix, IDOVEN, etc.) with `why_relevant` text genuinely citing the candidate's actual
> background per company - the XAI-in-healthcare thesis, the Madrid relocation interest, the OSS
> history - not generic pitches, confirming the combined discovery+judgement call works as
> intended. Confirmed dedupe/storage (10 new, 0 skipped), rendered the dashboard page for real (all
> 10 shown under "To review"), exercised all three feedback states plus a note-only save through
> the real Flask test client, confirmed persistence and correct regrouping afterward, confirmed the
> `saved=` confirmation indicator renders, confirmed `/history` picks up the new `discover:
> companies` cost-log stage with its label, and confirmed `company_feedback_examples_context()`
> renders the exact feedback block that would be fed into the next discovery run. Cleared the test
> feedback and its `events` rows afterward (it was fabricated for verification, not the
> candidate's real opinion) - the 10 discovered companies themselves are real and stayed, now
> sitting under "To review" for an actual first look.
>
> **A real limitation found, not a bug**: one of the ten results (Hologen AI) came back with a
> `careers_url` that doesn't actually match the company (it pointed at what looks like an
> unrelated company's job listing page) - a genuine WebSearch/model accuracy miss despite the
> prompt's explicit instruction to only return real, working URLs it's confident about (the same
> instruction Phase 3's job search prompt uses, which has the same known limitation). Not something
> code can fully guard against; worth knowing when using this feature that `careers_url` should be
> spot-checked, not trusted blindly.

- [x] Define a `CompanyLead` shape distinct from `Listing`: name, sector/stage, why relevant,
      careers/about page link, notes, source
- [x] Add a search-based discovery agent (reusing the Phase 3 pattern) that looks for companies/
      startups matching your criteria (sector, stage, location, mission) even when no specific job
      is advertised
- [x] Add a "why follow this" judgement step (a lighter version of the fit agent) that explains
      relevance rather than scoring against a specific job posting
- [x] Store company leads in their own table, with the same feedback mechanism as listings
      (relevant / not relevant / already known)
- [x] Add a "Companies to watch" section to the dashboard, separate from job listings
- [x] Feed company-lead feedback into the Phase 10 learning loop the same way as listing feedback

## Phase 16 — Make it reusable by others

> Audited the codebase for anything personal-specific still baked into code rather than config -
> most of it was already fine by this point (CV in gitignored `profile/cv.md` with an example
> template since Phase 8, criteria DB-only and dashboard-editable since Phase 8, sources
> config-driven since Phase 2), but found and fixed two real leftovers: `ingest.py`/
> `coordinator.py`/`sources/generic_rss.py` all hardcoded `"python"` as the RSS search-term
> fallback when no CLI argument was given - a personal default of the original author's, not a
> neutral one. Replaced with `profile.default_search_keywords()`, which uses the candidate's own
> first target role from criteria (falling back to a generic "software" only if no criteria are
> set yet at all). Similarly, `sources/adzuna.py`'s `DEFAULT_COUNTRY = "gb"` was a hardcoded
> Python constant rather than something a non-UK user could change without editing code - replaced
> with `default_country()`, reading an optional `ADZUNA_COUNTRY` from `.env` (documented in
> `.env.example`). Verified both live: `default_search_keywords()` correctly returned the real
> criteria's first role ("AI/ML Engineer") and a real RSS fetch using it returned real results;
> `adzuna.default_country()` correctly returned "gb" from the current `.env`.
>
> No separate "sample criteria" file was added - Phase 8's onboarding wizard already replaced
> `profile/criteria.example.yaml` as the fresh-setup path (see the Phase 8 follow-up note from
> 2026-09-26), and that file was deliberately removed rather than kept around unused. Someone
> cloning this fresh gets criteria entirely through the dashboard's onboarding form now, with no
> file to copy first.
>
> Wrote `README.md` (previously just the project title) - setup, running the coordinator vs. the
> separate company-discovery pipeline, how to add a new source (RSS via config, or a bespoke
> `fetch_listings()` module), where criteria/CV/`.env` configuration lives, and the cost-control
> knobs, all pointing back to `CLAUDE.md`/`tasks.md` for the full design rationale rather than
> duplicating it. Kept deliberately short per the phase's own brief, not a rewrite of `CLAUDE.md`.

- [x] Move all personal specifics (CV, criteria, source list, search query templates) out of code
      and into config/data files that a new user would edit
- [x] Write a short README: setup, how to add a new source agent, how criteria.yaml works
- [x] Add a sample/anonymized profile so someone else can try the system without your CV
- [x] Package as a Docker image/compose setup (added after the basics above, per user request
      2026-09-26) - lowers the "install uv/Python 3.12/dependencies correctly" barrier, distinct
      from what onboarding already solves (configuration, not installation). Needs volume mounts
      for `.env`, `data/job_search.db`, and `profile/` specifically, since onboarding and normal
      use write to all three at runtime - a naive image bake would lose everything on restart.

> `Dockerfile` follows the standard `uv` Docker pattern: a deps-only layer (`COPY pyproject.toml
> uv.lock` + `uv sync --frozen --no-install-project`) cached separately from a second layer that
> copies the rest of the source and syncs the project itself, so an ordinary code-only rebuild
> doesn't re-resolve dependencies. `docker-compose.yml` mounts `.env`, `data/`, `profile/`, and
> `config/` from the host - the same four paths the app reads/writes at runtime (`db.DB_PATH`,
> `profile.DEFAULT_PROFILE_DIR`, `generic_rss.CONFIG_PATH`, and `env_utils.ENV_PATH` all resolve
> relative to the installed package location, which lines up with these mount targets regardless
> of what directory the container's shell happens to be in).
>
> Two real things this surfaced, not just plumbing:
> - **Flask's dev server binds to 127.0.0.1 by default**, which is unreachable from outside a
>   container even with the port published. `webapp/__main__.py` now reads `HOST`/`FLASK_DEBUG`
>   from the environment (defaulting to the exact previous behavior - `127.0.0.1`, debug on - so
>   local `uv run` usage is unchanged), and the Dockerfile sets `HOST=0.0.0.0`/`FLASK_DEBUG=false`.
>   Debug mode's interactive debugger is a genuine remote-code-execution risk if it were ever
>   reachable beyond localhost, so turning it off for the packaged image (vs. local dev editing,
>   where the auto-reloader is worth keeping) was a deliberate, not incidental, choice.
> - **The dashboard has no authentication of its own** - anyone who can reach the port can see the
>   candidate's CV, criteria, and full cost history, and submit feedback. `docker-compose.yml`
>   binds the published port to `127.0.0.1` only by default (documented in a comment, and in the
>   README) rather than the more commonly-copy-pasted `"5000:5000"`, specifically so a reader who
>   skims past the explanation doesn't end up exposing it to their whole LAN by default.
> - Bind-mounting `.env` before it exists creates a directory at that path instead of a file (a
>   well-known Docker gotcha) and breaks the app confusingly - documented as a required `touch
>   .env` first step in both the compose file's top comment and the README.
>
> **Initial verification here was reasoning-only** (no Docker daemon was available at the time -
> checked the compose YAML parsed, confirmed the exact `ghcr.io/astral-sh/uv` tag actually exists
> via the GHCR registry API after an initial guessed version turned out wrong, checked the volume
> paths against the real path-resolution code). The user then ran it for real on their own machine
> and it worked - `docker compose up --build` succeeded and the dashboard came up - but the
> dashboard showed all the real listings/companies from this session's earlier live testing, which
> looked surprising until confirmed as correct: `docker-compose.yml` mounts `./data` from whatever
> directory `docker compose` is run in, and that directory was this project's own, already full of
> real data from every phase's live verification this session. Not a bug - exactly what makes
> results persist across container rebuilds - just surprising without the explanation.
>
> **Confirmed properly afterward with a real, separate instance**: assembled a second copy of the
> project (git-tracked files at their current, edited working-tree content, plus the three new
> untracked Docker files - i.e. exactly what a fresh clone after committing this work would have)
> in a directory with no pre-existing `.env`/`data`/`profile`, and ran it with a distinct compose
> project name and port so it couldn't collide with the user's already-running container. Hit a
> real environment quirk along the way worth recording: `docker` here is a **snap package**, which
> runs sandboxed and cannot see `/tmp` at all - regular shell commands (`ls`, `rsync`) saw the test
> files fine while `docker compose` reported "no such file" for the exact same path, since snap
> confinement gives it an entirely different filesystem view (its own private `/tmp`, only the real
> home directory shared through). Moving the test directory under `/home/alex/` instead of `/tmp`
> fixed it immediately - worth knowing if this project is ever debugged again on a similar
> snap-based setup. The separate instance then confirmed everything as intended: `GET /` 302-
> redirected to `/onboarding/step1` (the before_request gate correctly firing on empty `.env`/CV/
> criteria), the onboarding page rendered, and both `listings` and `company_leads` were genuinely
> `0` inside that container's own mounted `data/`. Torn down completely afterward (container,
> network, image, and the temporary directory - including one root-owned leftover file from
> running as the container's user, removed via a throwaway `alpine` container rather than `sudo`).

## Phase 17 — Stretch: scheduling

- [ ] Wire the coordinator to run on a schedule (cron or similar) with the spend guard from
      Phase 12 protecting unattended runs
- [ ] Decide what a scheduled run should do differently when nobody's watching the dashboard live
      (e.g. an email/notification summary pointing back to it)
