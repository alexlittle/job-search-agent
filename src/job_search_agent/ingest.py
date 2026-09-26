"""Runs the configured source agents once and stores results in the DB.

A stand-in for the Phase 11 coordinator - deliberately simple (call each source, store what
comes back, log activity and cost) so Phase 4's dedupe/logging can be exercised end to end
before any real agent orchestration exists.

Run with: uv run python -m job_search_agent.ingest [keywords-for-rss]
"""

import asyncio
import sqlite3
import sys

from job_search_agent import db
from job_search_agent.sources import adzuna, generic_rss, web_search


def ingest_rss(conn: sqlite3.Connection, keywords: str) -> None:
    listings = generic_rss.fetch_all(keywords=keywords)
    inserted = db.save_listings(conn, listings)
    db.log_event(
        conn,
        stage="fetch:rss",
        message=(
            f"Fetched {len(listings)} listing(s) from RSS feeds ({inserted} new) "
            f"for keywords={keywords!r}"
        ),
    )
    print(f"RSS: {len(listings)} fetched, {inserted} new.")


def ingest_adzuna(conn: sqlite3.Connection, role: str | None = None) -> None:
    if not adzuna.have_credentials():
        db.log_event(
            conn,
            stage="fetch:adzuna",
            message="Skipped - ADZUNA_APP_ID/ADZUNA_APP_KEY not set in .env",
        )
        print("Adzuna: skipped (no API credentials set in .env).")
        return

    listings = adzuna.fetch_all(role=role)
    inserted = db.save_listings(conn, listings)
    db.log_event(
        conn,
        stage="fetch:adzuna",
        message=f"Fetched {len(listings)} listing(s) from Adzuna ({inserted} new)",
    )
    print(f"Adzuna: {len(listings)} fetched, {inserted} new.")


async def ingest_web_search(conn: sqlite3.Connection, role: str | None) -> None:
    listings, costs = await web_search.search_all(role)
    inserted = db.save_listings(conn, listings)
    db.log_event(
        conn,
        stage="fetch:web_search",
        message=f"Found {len(listings)} listing(s) via web search ({inserted} new)",
    )
    for cost in costs:
        db.log_cost(
            conn,
            stage="fetch:web_search",
            model=cost.model,
            num_turns=cost.num_turns,
            cost_usd=cost.cost_usd,
            detail=cost.detail,
        )
    total_cost = sum(c.cost_usd for c in costs)
    print(f"Web search: {len(listings)} found, {inserted} new (${total_cost:.4f}).")


def main() -> None:
    keywords = sys.argv[1] if len(sys.argv) > 1 else "python"
    with db.connect() as conn:
        ingest_rss(conn, keywords=keywords)
        ingest_adzuna(conn, role=None)
        asyncio.run(ingest_web_search(conn, role=None))


if __name__ == "__main__":
    main()
