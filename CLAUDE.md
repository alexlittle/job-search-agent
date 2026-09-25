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
should pass the key explicitly via `env={"ANTHROPIC_API_KEY": ...}` rather than relying on
whatever the ambient environment happens to be authenticated as. See `src/job_search_agent/hello_agent.py`
for the pattern.

## Architecture

Package layout is `src/job_search_agent/` (uv-managed, src-layout, Python >=3.12). The pipeline is
being built in this shape (see `tasks.md` for the full phase-by-phase breakdown and current
status):

```
sources (structured feeds/APIs + general web search) -> normalize+dedupe (SQLite)
  -> rule-based pre-filter -> fit agent (Haiku coarse pass) -> fit agent (Sonnet detailed pass)
  -> report output -> user feedback (relevant / not relevant) -> feeds back into future prompts
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
  optional hardening.
- All personal data (CV, criteria, source list) is meant to live in config/data files, not
  hardcoded, so the project stays reusable by someone other than the original user (this is an
  explicit goal, not just good practice, per `docs/brief.md`).
