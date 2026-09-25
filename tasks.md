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

- [ ] Build a coordinator that runs the whole pipeline (sources → filter → Haiku → Sonnet →
      report) as one orchestrated flow, matching the course's coordinator pattern
- [ ] Add per-agent turn caps so a bad run can't loop indefinitely
- [ ] Add basic logging of what the coordinator did at each stage

## Phase 12 — Cost controls & observability

- [ ] Switch the Phase 6/7 fit-agent calls to the Anthropic Message Batches API (submit a batch,
      poll for completion, retrieve results) instead of one-by-one synchronous calls — 50%
      cheaper for the same requests, using the plain `anthropic` Python SDK rather than
      `claude-agent-sdk` (which is built for synchronous tool-use loops, not batch submission)
- [ ] Add prompt caching for the profile/criteria block (identical across every fit-agent call in
      a run)
- [ ] Track and print total run cost (calls, tokens, $ estimate) at the end of every run
- [ ] Add a configurable max-listings-per-run / max-spend-per-run guard — this matters more once
      Phase 3's open-ended search queries are in the mix

## Phase 13 — Second structured source agent (Adzuna API)

- [ ] Implement an Adzuna API fetcher producing the same `Listing` shape from Phase 2
- [ ] Plug it into the existing pipeline with no changes needed downstream — proves the
      pluggable-source design actually works
- [ ] Confirm dedupe correctly merges overlapping postings across all sources (RSS, search,
      Adzuna)

## Phase 14 — Validation/retry loop for uncertain calls

- [ ] For listings Sonnet marks "uncertain" (e.g. snippet too thin to judge), fetch the full job
      description page and re-run the fit check with fuller context
- [ ] Cap retries so this can't spiral in cost
- [ ] Confirm uncertain cases actually get resolved (or explicitly stay unresolved) rather than
      silently guessed at

## Phase 15 — Company/startup discovery agent

This is a different kind of output from a job listing: not "here's a role to apply for" but
"here's a company worth following, that might be worth a speculative application."

- [ ] Define a `CompanyLead` shape distinct from `Listing`: name, sector/stage, why relevant,
      careers/about page link, notes, source
- [ ] Add a search-based discovery agent (reusing the Phase 3 pattern) that looks for companies/
      startups matching your criteria (sector, stage, location, mission) even when no specific job
      is advertised
- [ ] Add a "why follow this" judgement step (a lighter version of the fit agent) that explains
      relevance rather than scoring against a specific job posting
- [ ] Store company leads in their own table, with the same feedback mechanism as listings
      (relevant / not relevant / already known)
- [ ] Add a "Companies to watch" section to the dashboard, separate from job listings
- [ ] Feed company-lead feedback into the Phase 10 learning loop the same way as listing feedback

## Phase 16 — Make it reusable by others

- [ ] Move all personal specifics (CV, criteria, source list, search query templates) out of code
      and into config/data files that a new user would edit
- [ ] Write a short README: setup, how to add a new source agent, how criteria.yaml works
- [ ] Add a sample/anonymized profile so someone else can try the system without your CV

## Phase 17 — Stretch: scheduling

- [ ] Wire the coordinator to run on a schedule (cron or similar) with the spend guard from
      Phase 12 protecting unattended runs
- [ ] Decide what a scheduled run should do differently when nobody's watching the dashboard live
      (e.g. an email/notification summary pointing back to it)
