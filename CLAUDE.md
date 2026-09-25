# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A customisable multi-agent job search assistant, built incrementally with the
[Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python). It finds job listings
and companies worth watching and scores them against the user's CV/preferences — it never applies
to anything on the user's behalf. See `docs/brief.md` for the original brief and design rationale, and
`tasks.md` for the phased build plan this project is following (check items off there as they're
completed — **do not build ahead of the current phase** without the user's agreement; this project
is deliberately being built step by step so the user can follow how each piece works).

## Commands

```bash
uv sync                                    # install/update dependencies
uv run python -m job_search_agent.<module> # run a script from src/job_search_agent/
uv add <package>                           # add a new dependency
```

There is no test suite, lint config, or build step yet — these will be introduced as later phases
in `tasks.md` need them. Don't add tooling (pytest, ruff, etc.) speculatively; add it in the phase
that actually needs it.

## Authentication

Scripts authenticate to Claude with a dedicated Anthropic Console API key (`ANTHROPIC_API_KEY` in
`.env`, gitignored), **not** the ambient `claude` CLI login used for interactive Claude Code
sessions on this machine. This is intentional: the project's cost-control design (spend caps,
model tiering, Batch API) assumes metered Console billing, so every `ClaudeAgentOptions` call
should pass the key explicitly via `env=anthropic_env()` (from `job_search_agent.claude_client`)
rather than relying on whatever the ambient environment happens to be authenticated as.

Similarly, `CONTACT_EMAIL` in `.env` is required before any HTTP fetch to an external site/API —
built into a User-Agent string via `job_search_agent.user_agent.build_user_agent()` — so that
someone else running this project sends their own contact details, not the original author's.

Any agent using a tool that needs approval (e.g. `WebSearch`) must set
`permission_mode="bypassPermissions"` on `ClaudeAgentOptions` — without it, tool calls hang
waiting for interactive approval that never comes in an unattended script. See
`src/job_search_agent/sources/web_search.py` for the pattern.

## Architecture

Package layout is `src/job_search_agent/` (uv-managed, src-layout, Python >=3.12). The pipeline is
being built in this shape (see `tasks.md` for the full phase-by-phase breakdown and current
status):

```
sources (structured feeds/APIs + general web search) -> normalize+dedupe (SQLite)
  -> rule-based pre-filter -> fit agent (Haiku coarse pass) -> fit agent (Sonnet detailed pass)
  -> local web dashboard (Flask) -> feedback buttons (relevant / not relevant) on the dashboard
  -> feeds back into future prompts
```

A few design decisions that shape how new code should fit in:

- **Model tiering is load-bearing, not incidental.** Cheap/fast models (Haiku) do the bulk
  first-pass filtering; the pricier model (Sonnet) only ever sees what already survived cheaper
  filters. Any new LLM-touching stage should default to the cheapest model that can do the job.
- **Sources are pluggable and must share a common shape.** Every job source (RSS, API, or
  general web search) produces the same `Listing` shape so the rest of the pipeline is
  source-agnostic. Company/startup discovery is a deliberately separate `CompanyLead` shape and
  pipeline branch (different judgement: "worth following" vs. "fits this specific posting"), not
  a variant of `Listing`.
- **Nothing here applies to jobs.** This is a triage/reporting tool only — don't add
  auto-apply, auto-submit, or account-automation behaviour for job boards (LinkedIn in particular
  explicitly prohibits scraping/automation; it's handled via the user's own email job alerts,
  outside this system).
- **Cost controls are part of the design, not an afterthought**: turn caps, spend guards, and
  prompt caching for the repeated profile/criteria block are explicit phases in `tasks.md`, not
  optional hardening. The fit-agent stages (Phase 6/7) are built first as ordinary synchronous
  calls, then switched to the Anthropic Message Batches API in Phase 12 — that's a deliberate
  two-step sequence (get it working, then make it cheaper), not an oversight if you find
  synchronous calls still in place.
- All personal data (CV, source list) is meant to live in config/data files, not hardcoded, so
  the project stays reusable by someone other than the original user (this is an explicit goal,
  not just good practice, per `docs/brief.md`). Plain RSS sources are meant to be addable via a
  config file alone (no code); only bespoke API sources need actual code, via a documented
  `fetch_listings() -> list[Listing]` plugin interface. **Criteria are the exception** — as of
  Phase 8 they live in the DB (`db.get_criteria`/`save_criteria`), seeded once from
  `profile/criteria.yaml` via `profile.load_criteria()`. Editing the YAML file after that point
  has no effect; the dashboard's Criteria page is how you change it now.
- Results are viewed, criteria are edited, and feedback is given through a local Flask dashboard
  (`src/job_search_agent/webapp/`) reading straight from the SQLite store (Phase 8/9) — there is
  no separate Markdown report output. Run with `uv run python -m job_search_agent.webapp`.
  Flask's debug-mode auto-reloader picks up code changes; when starting/stopping it in a script
  or tool call, use a mechanism that survives the call boundary (this project's dev sessions
  found that plain `&`/`nohup`/`disown` inside a single shell invocation does not).
- The dashboard partitions every listing into exactly one of five buckets, checked in this order
  (see the module docstring and `HIDDEN_WHERE`/`MAIN_WHERE`/`EXCLUDED_WHERE`/`REJECTED_WHERE`/
  `PENDING_WHERE` in `webapp/results.py`): hidden (`hidden_at` set — takes priority over
  everything) → rejected (`feedback = 'not_relevant'`) → main (`feedback = 'relevant'`, or unset
  with a strong/possible Sonnet status) → excluded (unset feedback, pipeline-excluded status) →
  pending (not scored yet). **These WHERE-clause constants are the single source of truth** —
  both the pages and the homepage stats are built from them, specifically because an earlier
  version let the stats and the page queries drift apart (double-counting listings that were
  both system-excluded and user-rejected) until real usage surfaced it. Changing what counts as
  "excluded" etc. means changing the constant, not one query site.
  - `/` — full cards (`templates/_listing_card.html`), unpaginated, deliberately: meant to stay
    small (only strong/possible + your own overrides, shown under a "Your picks" fallback
    section when a relevant-marked listing's status isn't strong/possible).
  - `/excluded`, `/rejected`, `/hidden` — share one template (`templates/listing_table.html`):
    compact rows, paginated 25/page via `_fetch()`'s `page` argument. Expand/collapse is a plain
    row + an explicit "Show details"/"Hide details" button (`toggleDetails()`, the one piece of
    real JS in the project, defined once in `base.html`) — **not** a native `<details>` element;
    an earlier version used one and real usage found "click anywhere on the row toggles it,
    except the title" not discoverable, so it was replaced with an explicit control.
  - All four views share `templates/_listing_detail.html` (rationale/matched/concerns/reason +
    the feedback form: note, relevant/not-relevant, save-note) and `templates/_hide_button.html`
    (Hide/Unhide, always visible in the row/card header, not buried in the expanded detail — an
    earlier version put it in the detail panel with a JS confirm dialog, which took three clicks
    for an action that's trivially reversible; now one click, no dialog). Extend these partials,
    not each page, so controls can't drift out of sync between views.
  - Feedback and hidden-state are independent: a listing can be `feedback='not_relevant'` *and*
    hidden at the same time, or hidden with no opinion recorded at all. Hiding is about dashboard
    visibility; feedback is about relevance. Don't conflate the two into one column.
  - Every mutating route (`give_feedback`, `hide_listing`, `unhide_listing`) takes a `next` value
    from a hidden form field (not `request.referrer`, which isn't reliable) and redirects back to
    it with `?saved=<id>` appended (via `_redirect_with_saved`). `_listing_detail.html` shows an
    inline "Saved" confirmation for that listing, and on `listing_table.html` the matching row
    auto-expands (`{% if saved_id != l.id %}hidden{% endif %}`) so the confirmation is visible
    immediately rather than landing inside a collapsed panel.
- A first-run onboarding wizard (`src/job_search_agent/webapp/onboarding.py`) gates the dashboard
  via a `before_request` hook on missing `.env` values, a missing CV file, or missing criteria —
  checked fresh on every request, not cached. It is **not** a gate on everything the wizard
  collects: the schedule-frequency step is captured but doesn't block dashboard access if unset,
  since nothing else depends on it yet (Phase 17 will). If adding a new onboarding step, decide
  deliberately whether it should be a hard gate — making everything one blocks re-entry to the
  dashboard for already-configured users the moment any single optional field is unset.
- The SQLite store (`data/job_search.db`, gitignored, see `src/job_search_agent/db.py`) holds
  more than listings: an `events` table is a running activity log (what each pipeline stage did
  and, once Phase 6/7 exist, why a listing was scored the way it was), and a `cost_log` table
  records every LLM call's cost. Any new LLM-calling or fetching code should write to these
  rather than only printing to console — the dashboard is meant to surface this history, not
  just final results. `src/job_search_agent/ingest.py` is a temporary stand-in for the Phase 11
  coordinator; expect it to be superseded once that phase exists.
- Dedupe key is normalized (title, company) — not URL, since the same posting on two different
  boards has two different URLs.
