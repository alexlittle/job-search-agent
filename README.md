# job-search-agent

A customisable multi-agent job search assistant, built with the
[Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python). It finds job listings
and companies worth watching and scores them against your CV/preferences.

**It never applies to anything on your behalf.** This is a triage/reporting tool: it fetches,
filters, scores, and shows you a dashboard. You decide what to do with any of it.

## How it works

```
sources (RSS feeds, Adzuna API, Claude web search) -> normalize+dedupe (SQLite)
  -> rule-based pre-filter -> fit agent (Haiku coarse pass) -> fit agent (Sonnet detailed pass)
  -> local web dashboard -> feedback buttons (relevant / not relevant)
  -> feeds back into future runs
```

Companies/startups worth following (as opposed to a specific job posting) are a separate,
independent pipeline - see [Company discovery](#company-discovery-separate-pipeline) below.

Cheap/fast models (Haiku) do the bulk first-pass filtering; the pricier model (Sonnet) only ever
sees what already survived the cheaper filters and the rule-based pre-filter. See `CLAUDE.md` and
`tasks.md` for the full design rationale and phase-by-phase build history.

## Setup

### Option A: Docker

```bash
touch .env   # required first - see the comment at the top of docker-compose.yml for why
docker compose up --build
```

Then open <http://localhost:5000> - a first-run onboarding wizard walks you through everything
(Anthropic API key, contact email, CV upload, job-search criteria). `.env`, `data/` (the SQLite
store), `profile/` (your CV/criteria), and `config/` (source feeds) are all mounted from this
directory into the container, so everything the wizard/dashboard writes persists across restarts
and rebuilds. The dashboard is bound to `127.0.0.1` only by default - it has no login of its own,
so see the comment in `docker-compose.yml` before changing that.

To run the fetch/scoring pipelines (they're not web servers, so they're one-off commands against
the same container/volumes rather than a second service):

```bash
docker compose run --rm dashboard uv run python -m job_search_agent.coordinator
docker compose run --rm dashboard uv run python -m job_search_agent.companies
```

### Option B: Local Python

Requires Python 3.12+ and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync
```

Then start the dashboard - the same onboarding wizard as above:

```bash
uv run python -m job_search_agent.webapp
```

You'll need an [Anthropic Console API key](https://platform.claude.com/) (not your claude.ai
login - see `CLAUDE.md`'s "Authentication" section for why), and it's worth setting a spend cap on
that account directly, in addition to this project's own app-level guards (see
[Cost controls](#cost-controls) below).

## Running the pipeline

The dashboard only shows results - fetching and scoring happens via the coordinator:

```bash
uv run python -m job_search_agent.coordinator                  # fetch, filter, score everything
uv run python -m job_search_agent.coordinator --no-web-search   # skip the paid web-search step
uv run python -m job_search_agent.coordinator "data scientist"  # override the RSS search term
```

There's no scheduler built in yet (see `tasks.md` Phase 17) - run it by hand, or wire it into cron
yourself for now.

## Adding a job source

- **A plain RSS feed** needs no code - add an entry to `config/sources.yaml` (see the comments at
  the top of that file for the supported field shapes).
- **Anything else** (an API needing auth, a non-RSS response format, etc.) needs a small module in
  `src/job_search_agent/sources/` exposing `fetch_listings(...) -> list[Listing]` - see
  `src/job_search_agent/sources/adzuna.py` for a real example, or the docstring in
  `src/job_search_agent/sources/__init__.py`. Wire it into `ingest.py` and `coordinator.py`
  alongside the existing sources once it's working standalone.

Either way, a new source just needs to produce `Listing` objects (`src/job_search_agent/
listing.py`) - dedupe, filtering, and scoring are all source-agnostic.

## Configuration

- **Criteria** (target roles, locations, salary, must-haves, dealbreakers, keywords) live in the
  database, set via the dashboard's Criteria page or the onboarding wizard - not a YAML file you
  hand-edit. `profile/criteria.yaml` still works as a one-time seed if you'd rather write one by
  hand and skip the web form, but it's entirely optional.
- **Your CV** lives in `profile/cv.md` (gitignored - never committed). Copy `profile/
  cv.example.md` as a starting point, or use the dashboard's onboarding upload step, which
  extracts and reformats a PDF/DOCX for you.
- **`.env`** (copy `.env.example`) holds your Anthropic API key, contact email (sent in the
  User-Agent header to external sites/APIs - use your own, not the original author's), optional
  Adzuna API credentials, and the cost-control settings below.

## Cost controls

- `MAX_LISTINGS_PER_RUN` (default 50) caps how many listings a single Haiku/Sonnet batch takes on
  per run - the rest wait for next time.
- `MAX_SPEND_PER_RUN_USD` (default $2.00) is a pessimistic pre-flight worst-case estimate checked
  before a batch is submitted; it raises rather than submits if exceeded.
- Both sit underneath whatever spend cap you set directly on your Anthropic Console account -
  that's the real backstop, this is a second line of defense.
- The Haiku/Sonnet fit-agent calls run through the Anthropic Message Batches API (50% cheaper than
  synchronous calls) with prompt caching on the shared CV/criteria/feedback block.

## Company discovery (separate pipeline)

Companies/startups worth following - even with no specific job advertised - are a distinct
pipeline from job listings, deliberately **not** wired into the coordinator above:

```bash
uv run python -m job_search_agent.companies
```

New companies worth watching turn up far less often than new job postings, so this is meant to run
on its own, much less frequent schedule. Results show up on the dashboard's Companies page, with
their own 3-way feedback (relevant / not relevant / already known).

## License

GPL-3.0 - see `LICENSE`.
