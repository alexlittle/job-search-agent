"""Finds job listings via Claude's web search tool - broader coverage than any single feed/API,
catching postings on ATS platforms, company career pages, or niche boards not otherwise
configured. This is the source agent from tasks.md Phase 3, added specifically because a curated
feed/API list will always miss things.

Unlike the plain-Python RSS sources, this makes real LLM calls (with web search) and costs real
money per query - a single role search here runs several times the cost of fetching an entire RSS
feed. Run it more sparingly than the free sources; see tasks.md Phase 12 for cost controls still
to come (this module has no spend guard yet).

Run with: uv run python -m job_search_agent.sources.web_search [role]
(omit role to search once per role in profile/criteria.yaml)
"""

import asyncio
import sys

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from job_search_agent.claude_client import anthropic_env
from job_search_agent.listing import Listing
from job_search_agent.profile import Criteria, load_profile

MODEL = "claude-haiku-4-5-20251001"
SOURCE_NAME = "web_search"
MAX_RESULTS_PER_ROLE = 5

LISTING_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "listings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "company": {"type": "string"},
                        "url": {"type": "string"},
                        "location": {"type": "string"},
                        "posted_date": {"type": ["string", "null"]},
                        "description": {"type": "string"},
                    },
                    "required": ["title", "company", "url", "location", "description"],
                },
            }
        },
        "required": ["listings"],
    },
}


def build_prompt(role: str, criteria: Criteria) -> str:
    locations = ", ".join(criteria.locations) or "no location preference"
    boost = ", ".join(criteria.keywords_boost)
    avoid = ", ".join(criteria.keywords_avoid)

    lines = [
        f"Search the web for current, genuine job openings for the role: {role}.",
        f"Acceptable locations: {locations}.",
    ]
    if boost:
        lines.append(f"These are a plus, not a requirement: {boost}.")
    if avoid:
        lines.append(f"Avoid roles mentioning: {avoid}.")
    lines.append(
        "\nPrefer results from company career pages, ATS platforms (Greenhouse, Lever, "
        "SmartRecruiters, Workable, etc.) or smaller/niche boards - these are more likely to "
        "give a direct link to a real, individual posting. Avoid linking to generic "
        "search/aggregator pages on sites like Indeed or LinkedIn.\n"
        "Only include a listing if you have a specific, working URL for that exact posting. If "
        f"you can't find any genuine individual postings, return an empty list rather than "
        f"guessing. Return at most {MAX_RESULTS_PER_ROLE} results."
    )
    return "\n".join(lines)


async def search_for_role(role: str, criteria: Criteria) -> list[Listing]:
    options = ClaudeAgentOptions(
        model=MODEL,
        max_turns=6,
        tools=["WebSearch"],
        permission_mode="bypassPermissions",
        output_format=LISTING_SCHEMA,
        env=anthropic_env(),
    )

    listings: list[Listing] = []
    async for message in query(prompt=build_prompt(role, criteria), options=options):
        if isinstance(message, ResultMessage) and message.structured_output:
            for item in message.structured_output.get("listings", []):
                listings.append(
                    Listing(
                        source=SOURCE_NAME,
                        title=item.get("title", ""),
                        company=item.get("company", ""),
                        url=item.get("url", ""),
                        location=item.get("location", ""),
                        posted_date=item.get("posted_date"),
                        description=item.get("description", ""),
                    )
                )
    return listings


async def search_all(role: str | None = None) -> list[Listing]:
    profile = load_profile()
    roles = [role] if role else profile.criteria.roles

    listings: list[Listing] = []
    for one_role in roles:
        listings.extend(await search_for_role(one_role, profile.criteria))
    return listings


def main() -> None:
    role = sys.argv[1] if len(sys.argv) > 1 else None
    listings = asyncio.run(search_all(role))
    for listing in listings:
        print(f"- [{listing.company}] {listing.title} ({listing.location})")
        print(f"  {listing.url}")
    print(f"\n{len(listings)} listing(s) found via web search.")


if __name__ == "__main__":
    main()
