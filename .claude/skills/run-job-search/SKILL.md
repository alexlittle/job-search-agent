---
name: run-job-search
description: Run the job search pipeline and/or company discovery agent. Use whenever the user asks to run the job search, run both agents, run the pipeline, search for jobs, discover companies, check on running agents, or start the dashboard. Also trigger on 'run the coordinator', 'find new jobs', 'find companies to watch', or any request to execute the pipeline scripts.
---

# Run Job Search Agents

This skill runs the job search pipeline and company discovery agent. These are two independent pipelines — one finds and scores job listings, the other discovers companies worth watching for speculative applications. All commands use `uv run` from the project root.

## Pre-flight checks

Before running either agent, verify the essentials exist:

```bash
ls .env profile/cv.md
```

Both files are required — `.env` holds `ANTHROPIC_API_KEY` and `CONTACT_EMAIL`, and `profile/cv.md` is the candidate profile the agents score against. If either is missing, tell the user and stop.

## The two agents

### 1. Job search pipeline (coordinator)

The main pipeline that finds and scores job listings. It runs five stages in sequence:

1. **Fetch listings** — RSS feeds, Adzuna API, and optionally web search
2. **Pre-filter** — rule-based filtering on keywords, location, etc.
3. **Haiku coarse pass** — cheap bulk LLM pass to reject obvious mismatches (Batches API)
4. **Sonnet detailed pass** — deeper scoring of survivors (Batches API)
5. **Retry pass** — resolves uncertain verdicts by fetching the full posting page

```bash
uv run python -m job_search_agent.coordinator [keywords] [--no-web-search]
```

- Omit `keywords` to use the default from the user's saved criteria
- `--no-web-search` skips the web search stage (cheaper and faster — RSS + Adzuna only)
- The Batches API stages poll for up to 30 minutes each, so the full pipeline can take a while

### 2. Company discovery

Finds companies and startups worth watching for speculative applications — a different judgement from job listings. Deliberately separate from the coordinator because new companies worth following turn up far less often than new job postings.

**Important:** Use `job_search_agent.companies` (not `job_search_agent.sources.company_discovery`) — the `companies` module is the proper entry point that saves results to the database and logs costs. The `sources.company_discovery` module only prints to stdout.

```bash
uv run python -m job_search_agent.companies
```

This agent can be disabled from the dashboard's Settings page — if disabled, it exits immediately with a skip message.

## Running both agents together

When asked to run both, start them as background processes so they run in parallel:

```bash
uv run python -m job_search_agent.coordinator &
COORD_PID=$!
uv run python -m job_search_agent.companies &
COMPANY_PID=$!
echo "Coordinator PID: $COORD_PID | Company discovery PID: $COMPANY_PID"
```

### Monitoring

Check whether both processes are still running:

```bash
ps -p $COORD_PID -o pid,etime,args 2>/dev/null; \
ps -p $COMPANY_PID -o pid,etime,args 2>/dev/null
```

Query recent pipeline events from the database:

```bash
uv run python -Ic "
from job_search_agent import db
with db.connect() as conn:
    rows = conn.execute('SELECT timestamp, stage, message FROM events ORDER BY timestamp DESC LIMIT 15').fetchall()
for r in rows:
    print(f'{r[0]}  [{r[1]}]  {r[2]}')
"
```

## After completion

Once the agents finish, report:

- Whether each agent succeeded or failed (check exit codes or process status)
- Total cost this run (from the pipeline's own output, or query `cost_log`)
- Summary of what was found (new listings, scores, new companies)
- Remind the user to check the dashboard for full results

### Starting the dashboard

If the user wants to see results and the dashboard isn't already running:

```bash
uv run python -m job_search_agent.webapp &
echo "Dashboard starting at http://127.0.0.1:5000"
```

Check if it's already running first: `lsof -i :5000 2>/dev/null`

## Cost awareness

The pipeline uses real Anthropic API credits. Key cost controls:

- **Web search** is the most expensive part of the coordinator — suggest `--no-web-search` for quick/cheap runs unless the user specifically wants it
- `MAX_SPEND_PER_RUN_USD` (default $2.00) and `MAX_LISTINGS_PER_RUN` (default 50) are configurable in `.env`
- Company discovery uses a single Haiku agent call with web search — typically a few cents

Always mention the cost in the completion report so the user can track spend.