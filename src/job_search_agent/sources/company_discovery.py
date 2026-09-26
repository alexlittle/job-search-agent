"""Finds companies/startups worth following - a different judgement from job listings (Phase 3):
"here's a company worth watching, might be worth a speculative application" rather than "here's
a role to apply for". Same WebSearch tool pattern as sources/web_search.py, but this is a single
combined call per run rather than one search per role: discovery and the "why follow this"
judgement happen together in one structured-output call (this is the "lighter version of the fit
agent" tasks.md Phase 15 asks for - there's no volume/tiering problem to solve here the way there
is for job listings, so a second LLM stage would just double the cost for no real benefit).

Deliberately NOT wired into coordinator.py - new companies/startups worth watching turn up far
less often than new job postings, so this is meant to run on its own, much less frequent schedule
(a real scheduler is still Phase 17, but the code is already structured for that: nothing here
runs unless this module - or companies.py, its entry point - is invoked directly).

Run with: uv run python -m job_search_agent.sources.company_discovery
"""

import asyncio

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from job_search_agent.claude_client import anthropic_env, call_with_retry
from job_search_agent.company_lead import CompanyLead
from job_search_agent.profile import Profile, load_profile
from job_search_agent.sources.web_search import SearchCost

MODEL = "claude-haiku-4-5-20251001"
SOURCE_NAME = "company_discovery"
MAX_RESULTS = 10

COMPANY_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "companies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "sector": {"type": "string"},
                        "stage": {"type": "string"},
                        "why_relevant": {"type": "string"},
                        "careers_url": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "required": [
                        "name", "sector", "stage", "why_relevant", "careers_url", "notes",
                    ],
                },
            }
        },
        "required": ["companies"],
    },
}


def build_prompt(profile: Profile, feedback_context: str) -> str:
    criteria = profile.criteria
    sectors = ", ".join(criteria.keywords_boost) or "no particular sector preference"
    locations = ", ".join(criteria.locations) or "no location preference"
    avoid = ", ".join(criteria.keywords_avoid)

    lines = [
        "Search the web for real companies or startups worth following for the candidate "
        "described below, even where they have no specific job opening advertised right now - "
        "the goal is speculative-application targets to watch, not open roles.",
        "",
        profile.as_prompt_context(),
    ]
    if feedback_context:
        lines += ["", feedback_context]
    lines += [
        "",
        f"Sectors/mission areas of interest: {sectors}.",
        f"Acceptable locations: {locations}.",
    ]
    if avoid:
        lines.append(f"Avoid sectors/companies related to: {avoid}.")
    lines.append(
        "\nFor each company, give:\n"
        "- name: the real company name\n"
        "- sector: a short sector/mission description\n"
        "- stage: e.g. seed, series A, growth, established, unknown\n"
        "- why_relevant: a specific, concrete reason *this* candidate should watch *this* "
        "company - reference their actual background, not a generic pitch\n"
        "- careers_url: their real careers or about page - a working URL, not a generic search "
        "results page\n"
        "- notes: anything else worth knowing (recent funding, news, etc.), or an empty string\n"
        "Only include genuine companies you're confident exist and that you found real "
        "information about - if you can't find enough strong candidates, return fewer rather "
        f"than padding the list. Return at most {MAX_RESULTS} companies."
    )
    return "\n".join(lines)


async def _run_discovery(profile: Profile, feedback_context: str) -> tuple[list[CompanyLead], SearchCost]:
    options = ClaudeAgentOptions(
        model=MODEL,
        max_turns=6,
        tools=["WebSearch"],
        permission_mode="bypassPermissions",
        output_format=COMPANY_SCHEMA,
        env=anthropic_env(),
    )

    leads: list[CompanyLead] = []
    cost = SearchCost(model=MODEL, num_turns=0, cost_usd=0.0, detail="company discovery")
    prompt = build_prompt(profile, feedback_context)
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            cost.num_turns = message.num_turns
            cost.cost_usd = message.total_cost_usd or 0.0
            if message.structured_output:
                for item in message.structured_output.get("companies", []):
                    leads.append(
                        CompanyLead(
                            name=item.get("name", ""),
                            sector=item.get("sector", ""),
                            stage=item.get("stage", ""),
                            why_relevant=item.get("why_relevant", ""),
                            careers_url=item.get("careers_url", ""),
                            notes=item.get("notes", ""),
                            source=SOURCE_NAME,
                        )
                    )
    return leads, cost


async def discover_companies(feedback_context: str = "") -> tuple[list[CompanyLead], SearchCost]:
    profile = load_profile()
    return await call_with_retry(lambda: _run_discovery(profile, feedback_context))


def main() -> None:
    leads, cost = asyncio.run(discover_companies())
    for lead in leads:
        print(f"- {lead.name} ({lead.sector}, {lead.stage})")
        print(f"    why: {lead.why_relevant}")
        print(f"    {lead.careers_url}")
    print(f"\n{len(leads)} compan(y/ies) found. (${cost.cost_usd:.4f} total cost)")


if __name__ == "__main__":
    main()
