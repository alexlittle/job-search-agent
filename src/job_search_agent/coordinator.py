"""Runs the whole pipeline as one orchestrated flow: sources (RSS, Adzuna, web search) ->
pre-filter -> Haiku -> Sonnet.
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
(omit keywords for the default "python"; web search runs once per role in the criteria and costs
real money each time, so it's easy to skip for a quick/free RSS-only run)
"""

import asyncio
import sys
from datetime import UTC, datetime

from job_search_agent import db
from job_search_agent.filters import run_filters
from job_search_agent.fit.haiku import run_haiku_pass
from job_search_agent.fit.sonnet import run_sonnet_pass
from job_search_agent.ingest import ingest_adzuna, ingest_rss, ingest_web_search

STAGE = "coordinator"


def _log(message: str) -> None:
    with db.connect() as conn:
        db.log_event(conn, stage=STAGE, message=message)


async def run_pipeline(keywords: str = "python", include_web_search: bool = True) -> None:
    started_at = datetime.now(UTC).isoformat()
    _log(f"Pipeline run started (keywords={keywords!r}, web_search={include_web_search})")

    print("== Fetching listings ==")
    with db.connect() as conn:
        ingest_rss(conn, keywords=keywords)
        ingest_adzuna(conn, role=None)
        if include_web_search:
            await ingest_web_search(conn, role=None)
    _log("Finished fetching listings")

    print("\n== Pre-filtering ==")
    run_filters()
    _log("Finished pre-filter")

    print("\n== Haiku coarse pass ==")
    await run_haiku_pass()
    _log("Finished Haiku pass")

    print("\n== Sonnet detailed pass ==")
    await run_sonnet_pass()
    _log("Finished Sonnet pass")

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
    keywords = positional[0] if positional else "python"
    asyncio.run(run_pipeline(keywords=keywords, include_web_search=include_web_search))


if __name__ == "__main__":
    main()
