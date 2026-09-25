"""Coarse fit judgement: Haiku reads one listing plus the user's profile and gives a quick
yes/maybe/no verdict with a one-line reason. Deliberately cheap and fast - Sonnet (Phase 7) only
looks at what this stage doesn't rule out, so a wrong "no" here is costly (the listing never gets
a proper look) while a wrong "yes"/"maybe" just costs a bit of Sonnet budget later. The prompt
reflects that asymmetry explicitly.

Run with: uv run python -m job_search_agent.fit.haiku
"""

import asyncio
import sqlite3
from dataclasses import dataclass

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from job_search_agent import db
from job_search_agent.claude_client import anthropic_env
from job_search_agent.profile import Profile, feedback_examples_context, load_profile

MODEL = "claude-haiku-4-5-20251001"
STAGE = "haiku"

VERDICT_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["yes", "maybe", "no"]},
            "reason": {"type": "string"},
        },
        "required": ["verdict", "reason"],
    },
}


@dataclass
class FitResult:
    verdict: str
    reason: str
    cost_usd: float
    num_turns: int


def build_prompt(listing: sqlite3.Row, profile: Profile, feedback_context: str = "") -> str:
    feedback_block = f"{feedback_context}\n\n" if feedback_context else ""
    return (
        f"{profile.as_prompt_context()}\n\n"
        f"{feedback_block}"
        "## Listing to judge\n"
        f"Title: {listing['title']}\n"
        f"Company: {listing['company']}\n"
        f"Location: {listing['location']}\n"
        f"Description: {listing['description']}\n\n"
        "Judge whether this listing is worth the candidate's attention, given their CV and "
        "criteria above. This is a fast first pass, not the final word - anything you don't "
        "rule out here gets a more careful review next, so a wrong 'yes' costs little but a "
        "wrong 'no' loses the listing for good. When genuinely unsure, prefer 'maybe' over 'no'.\n"
        "- 'yes' - clearly worth a closer look\n"
        "- 'maybe' - plausible but uncertain\n"
        "- 'no' - clearly not a fit (wrong domain, wrong seniority, a dealbreaker present, etc.)\n"
        "Give a one-sentence reason either way."
    )


async def score_listing(
    listing: sqlite3.Row, profile: Profile, feedback_context: str = ""
) -> FitResult:
    options = ClaudeAgentOptions(
        model=MODEL,
        max_turns=1,
        tools=[],
        output_format=VERDICT_SCHEMA,
        env=anthropic_env(),
    )

    verdict, reason, cost_usd, num_turns = "no", "No response", 0.0, 0
    prompt = build_prompt(listing, profile, feedback_context)
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            num_turns = message.num_turns
            cost_usd = message.total_cost_usd or 0.0
            if message.structured_output:
                verdict = message.structured_output.get("verdict", verdict)
                reason = message.structured_output.get("reason", reason)
    return FitResult(verdict=verdict, reason=reason, cost_usd=cost_usd, num_turns=num_turns)


async def run_haiku_pass() -> None:
    profile = load_profile()
    total_cost = 0.0
    counts = {"yes": 0, "maybe": 0, "no": 0}

    with db.connect() as conn:
        feedback_context = feedback_examples_context(conn)
        rows = conn.execute("SELECT * FROM listings WHERE status = 'pending_fit'").fetchall()
        for row in rows:
            result = await score_listing(row, profile, feedback_context)
            conn.execute(
                "UPDATE listings SET status = ? WHERE id = ?",
                (f"haiku_{result.verdict}", row["id"]),
            )
            db.log_verdict(
                conn,
                listing_id=row["id"],
                stage=STAGE,
                verdict=result.verdict,
                reason=result.reason,
            )
            db.log_cost(
                conn,
                stage=f"fit:{STAGE}",
                model=MODEL,
                num_turns=result.num_turns,
                cost_usd=result.cost_usd,
                detail=row["title"],
            )
            total_cost += result.cost_usd
            counts[result.verdict] = counts.get(result.verdict, 0) + 1
            print(f"[{result.verdict:>5}] {row['title'][:60]} - {result.reason}")

    print(
        f"\nScored {sum(counts.values())} listing(s): "
        f"{counts['yes']} yes, {counts['maybe']} maybe, {counts['no']} no. "
        f"(${total_cost:.4f} total cost)"
    )


def main() -> None:
    asyncio.run(run_haiku_pass())


if __name__ == "__main__":
    main()
