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

from job_search_agent import db
from job_search_agent.profile import company_feedback_examples_context
from job_search_agent.sources.company_discovery import discover_companies

STAGE = "discover:companies"


async def run_company_discovery() -> None:
    with db.connect() as conn:
        feedback_context = company_feedback_examples_context(conn)

    leads, cost = await discover_companies(feedback_context)

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
