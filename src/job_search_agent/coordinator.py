"""Runs the whole pipeline as one orchestrated flow: sources (RSS, Adzuna, web search) ->
pre-filter -> Haiku -> Sonnet -> retry (Phase 14, resolves Sonnet's "uncertain" verdicts with the
full posting page).
The Phase 11 coordinator - supersedes calling `ingest.py`, `filters.py`, `fit/haiku.py`, and
`fit/sonnet.py` by hand in sequence, matching the course's coordinator pattern (a single entry
point wiring the specialist agents together).

Per-agent turn/retry caps already exist at the point where each agent actually runs a Claude
call. Haiku/Sonnet (Phase 12) run as one Message Batches API submission each, not a per-listing
loop - a single failed request within a batch is logged and skipped rather than retried (see
`fit/haiku.py`/`fit/sonnet.py`), since the next coordinator run picks it back up anyway. Web
search (still a single synchronous `claude-agent-sdk` call, `max_turns=6`) uses
`claude_client.call_with_retry` instead, since there's no batch to fall back into if it fails.
`limits.py` adds the other half of "can't run away": `MAX_LISTINGS_PER_RUN` caps how many
listings a single Haiku/Sonnet batch takes on, and `MAX_SPEND_PER_RUN_USD` is a pre-flight
worst-case cost check before either batch is submitted.

Run with: uv run python -m job_search_agent.coordinator [keywords-for-rss] [--no-web-search]
(omit keywords to default to the candidate's own first target role from criteria; web search runs
once per role in the criteria and costs real money each time, so it's easy to skip for a
quick/free RSS-only run)

No stage here swallows an error - a network drop (this runs unattended via cron, often on a
laptop that sleeps/travels) still crashes the run with a full traceback and non-zero exit, so
cron's own log file keeps the real diagnostic detail. What's added here is a clean one-line
"failed during <stage>" event in the `events` table (visible on the dashboard's History page)
logged *before* that crash propagates, so knowing something broke - and roughly where - doesn't
require digging through a log file first. Whatever already ran before the failing stage is
already committed to the DB either way (nothing here is transactional across stages), so a
crash never rolls back or duplicates earlier progress in the same run.
"""

import asyncio
import sys
from datetime import UTC, datetime

from job_search_agent import db, profile
from job_search_agent.filters import run_filters
from job_search_agent.fit.haiku import run_haiku_pass
from job_search_agent.fit.retry import run_retry_pass
from job_search_agent.fit.sonnet import run_sonnet_pass
from job_search_agent.ingest import ingest_adzuna, ingest_rss, ingest_web_search

STAGE = "coordinator"


def _log(message: str) -> None:
    with db.connect() as conn:
        db.log_event(conn, stage=STAGE, message=message)


async def run_pipeline(keywords: str | None = None, include_web_search: bool = True) -> None:
    keywords = keywords or profile.default_search_keywords()
    started_at = datetime.now(UTC).isoformat()
    _log(f"Pipeline run started (keywords={keywords!r}, web_search={include_web_search})")

    stage = "startup"
    try:
        stage = "fetching listings"
        print("== Fetching listings ==")
        with db.connect() as conn:
            ingest_rss(conn, keywords=keywords)
            ingest_adzuna(conn, role=None)
            if include_web_search:
                await ingest_web_search(conn, role=None)
        _log("Finished fetching listings")

        stage = "pre-filtering"
        print("\n== Pre-filtering ==")
        run_filters()
        _log("Finished pre-filter")

        stage = "Haiku coarse pass"
        print("\n== Haiku coarse pass ==")
        await run_haiku_pass()
        _log("Finished Haiku pass")

        stage = "Sonnet detailed pass"
        print("\n== Sonnet detailed pass ==")
        await run_sonnet_pass()
        _log("Finished Sonnet pass")

        stage = "retrying uncertain verdicts"
        print("\n== Retrying uncertain verdicts ==")
        await run_retry_pass()
        _log("Finished retry pass")
    except Exception as exc:
        _log(f"Pipeline run FAILED during {stage}: {exc}")
        print(f"\n[error] Pipeline run failed during {stage}: {exc}", file=sys.stderr)
        print(
            "Whatever completed before this is already saved - check the dashboard's History "
            "page. Full traceback follows for the log file:",
            file=sys.stderr,
        )
        raise

    with db.connect() as conn:
        total_cost = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM cost_log WHERE timestamp >= ?", (started_at,)
        ).fetchone()[0]
    _log(f"Pipeline run finished (${total_cost:.4f} total cost)")
    print(f"\nPipeline run complete. Total cost this run: ${total_cost:.4f}")
    print("See the dashboard's History page for the full activity/cost log.")


def main() -> None:
    args = sys.argv[1:]
    include_web_search = "--no-web-search" not in args
    positional = [a for a in args if a != "--no-web-search"]
    keywords = positional[0] if positional else None
    asyncio.run(run_pipeline(keywords=keywords, include_web_search=include_web_search))


if __name__ == "__main__":
    main()
