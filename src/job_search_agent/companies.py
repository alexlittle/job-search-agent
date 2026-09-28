"""Standalone entry point for company/startup discovery (Phase 15) - the sibling of ingest.py/
coordinator.py for the job-listing pipeline, but deliberately never called from either of them.

New companies worth following turn up far less often than new job postings, so this is meant to
run on its own, much less frequent schedule for cost control - nothing here runs as a side effect
of running the job pipeline. A real scheduler is still Phase 17, but keeping this as its own
entry point means that phase can give the two pipelines independent cadences without any further
restructuring here.

Run with: uv run python -m job_search_agent.companies
"""

import asyncio
import sys

from job_search_agent import db, source_registry
from job_search_agent.profile import company_feedback_examples_context
from job_search_agent.sources.company_discovery import discover_companies

STAGE = "discover:companies"


async def run_company_discovery() -> None:
    with db.connect() as conn:
        if not source_registry.is_enabled(conn, "source:company_discovery"):
            db.log_event(conn, stage=STAGE, message="Skipped - disabled in Settings")
            print("Company discovery: skipped (disabled in Settings).")
            return
        feedback_context = company_feedback_examples_context(conn)

    try:
        leads, cost = await discover_companies(feedback_context)
    except Exception as exc:
        with db.connect() as conn:
            db.log_event(conn, stage=STAGE, message=f"Run FAILED: {exc}")
        print(f"\n[error] Company discovery failed: {exc}", file=sys.stderr)
        print("Full traceback follows for the log file:", file=sys.stderr)
        raise

    with db.connect() as conn:
        inserted = db.save_company_leads(conn, leads)
        db.log_event(
            conn,
            stage=STAGE,
            message=f"Found {len(leads)} compan(y/ies) via web search ({inserted} new)",
        )
        db.log_cost(
            conn,
            stage=STAGE,
            model=cost.model,
            num_turns=cost.num_turns,
            cost_usd=cost.cost_usd,
            detail=cost.detail,
        )

    print(f"Company discovery: {len(leads)} found, {inserted} new. (${cost.cost_usd:.4f} total cost)")
    print("See the dashboard's Companies page.")


def main() -> None:
    asyncio.run(run_company_discovery())


if __name__ == "__main__":
    main()
