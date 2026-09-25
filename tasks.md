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

- [ ] Implement cheap, non-LLM filters using `criteria.yaml` (location, dealbreaker keywords,
      obviously-wrong role type)
- [ ] Mark filtered-out listings in the DB with a reason, so nothing is silently dropped
- [ ] Confirm on real data that obviously irrelevant postings get filtered before any LLM call
      would happen

## Phase 6 — Fit agent v1 (coarse pass, Haiku)

> Built here as ordinary synchronous calls, one per listing, so it's easy to see what's
> happening. Phase 12 switches this and Phase 7 over to the Anthropic Message Batches API (50%
> cheaper, and nothing here needs an instant answer) once the synchronous version works.

- [ ] Build the first real fit agent: given one listing + your profile, ask Haiku for a coarse
      yes/no/maybe fit judgement with a one-line reason
- [ ] Define the structured output contract (e.g. JSON: `{verdict, reason}`)
- [ ] Run it over everything that survived Phase 5, store verdicts in the DB
- [ ] Print the cost/turn count for the run

## Phase 7 — Fit agent v2 (detailed pass, Sonnet)

- [ ] Take everything Haiku marked yes/maybe and send only those to Sonnet
- [ ] Ask for a detailed structured verdict: fit score, matched criteria, concerns, short
      rationale
- [ ] Store detailed verdicts in the DB alongside the coarse ones
- [ ] Compare cost of running Sonnet on everything vs. only on Haiku's survivors

## Phase 8 — Results dashboard

- [ ] Add Flask, set up a minimal local web app that reads directly from the SQLite store (no
      separate report file)
- [ ] Build a results page: matched listings grouped by score/verdict, with enough info to decide
      without opening the link (title, company, location, score, why, link)
- [ ] Move criteria (roles, locations, salary, must-haves, dealbreakers, keywords) into a DB
      table, seeded once from `profile/criteria.yaml`, and add a simple editing page on the
      dashboard — this is what makes "dynamically updatable criteria" (raised after Phase 4)
      actually more convenient than editing the YAML file, so it's built here rather than earlier
- [ ] Run the full pipeline end to end for the first time: fetch (RSS + search) → filter → score
      → view results in the dashboard

## Phase 9 — User feedback capture

- [ ] Add relevant/not-relevant buttons on the dashboard for each listing, writing feedback
      straight to the SQLite store
- [ ] Confirm feedback persists across runs and page reloads

## Phase 10 — Learning from feedback

- [ ] Pull accumulated feedback into the fit-agent prompt as examples ("here are jobs I said
      yes/no to before, and why, if known")
- [ ] Re-run the fit agent on a fresh batch and check whether verdicts noticeably reflect past
      feedback
- [ ] Decide how much feedback history to include (recency/cap) to keep prompt size sane

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
