"""Detailed fit judgement: Sonnet reads a listing, the user's profile, and Haiku's coarse
verdict, then gives a scored, itemised assessment. Only runs on what Haiku's coarse pass (Phase
6) didn't rule out - the whole point of model tiering is that the pricier model only ever sees
the subset worth a careful look.

Run with: uv run python -m job_search_agent.fit.sonnet
"""

import asyncio
import json
import sqlite3
from dataclasses import dataclass, field

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from job_search_agent import db
from job_search_agent.claude_client import anthropic_env
from job_search_agent.profile import Profile, feedback_examples_context, load_profile

MODEL = "claude-sonnet-5"
STAGE = "sonnet"

ASSESSMENT_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "score": {"type": "integer", "minimum": 0, "maximum": 100},
            "matched_criteria": {"type": "array", "items": {"type": "string"}},
            "concerns": {"type": "array", "items": {"type": "string"}},
            "rationale": {"type": "string"},
        },
        "required": ["score", "matched_criteria", "concerns", "rationale"],
    },
}


@dataclass
class Assessment:
    score: int = 0
    matched_criteria: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    rationale: str = "No response"
    cost_usd: float = 0.0
    num_turns: int = 0

    def bucket(self) -> str:
        if self.score >= 70:
            return "strong"
        if self.score >= 40:
            return "possible"
        return "weak"


def build_prompt(listing: sqlite3.Row, profile: Profile, feedback_context: str = "") -> str:
    feedback_block = f"{feedback_context}\n\n" if feedback_context else ""
    return (
        f"{profile.as_prompt_context()}\n\n"
        f"{feedback_block}"
        "## Listing to evaluate\n"
        f"Title: {listing['title']}\n"
        f"Company: {listing['company']}\n"
        f"Location: {listing['location']}\n"
        f"Description: {listing['description']}\n\n"
        "## First-pass note (a faster, cheaper model already looked at this)\n"
        f"Verdict: {listing['haiku_verdict']}\n"
        f"Reason: {listing['haiku_reason']}\n\n"
        "Give a careful, detailed assessment of fit:\n"
        "- score: 0-100, where 100 is an ideal match given the candidate's CV and criteria above\n"
        "- matched_criteria: specific things from the candidate's profile this listing actually "
        "satisfies (be specific about which criterion and why, not generic)\n"
        "- concerns: specific concerns or genuine uncertainties - if the description doesn't say "
        "enough to judge something (the first-pass note above may already flag one), say so "
        "rather than guessing\n"
        "- rationale: a short paragraph explaining the score"
    )


async def assess_listing(
    listing: sqlite3.Row, profile: Profile, feedback_context: str = ""
) -> Assessment:
    options = ClaudeAgentOptions(
        model=MODEL,
        max_turns=1,
        tools=[],
        output_format=ASSESSMENT_SCHEMA,
        env=anthropic_env(),
    )

    assessment = Assessment()
    prompt = build_prompt(listing, profile, feedback_context)
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            assessment.num_turns = message.num_turns
            assessment.cost_usd = message.total_cost_usd or 0.0
            if message.structured_output:
                out = message.structured_output
                assessment.score = out.get("score", 0)
                assessment.matched_criteria = out.get("matched_criteria", [])
                assessment.concerns = out.get("concerns", [])
                assessment.rationale = out.get("rationale", assessment.rationale)
    return assessment


async def run_sonnet_pass() -> None:
    profile = load_profile()
    total_cost = 0.0
    scored = 0

    with db.connect() as conn:
        feedback_context = feedback_examples_context(conn)
        rows = conn.execute(
            """
            SELECT listings.*, verdicts.verdict AS haiku_verdict, verdicts.reason AS haiku_reason
            FROM listings
            JOIN verdicts ON verdicts.listing_id = listings.id AND verdicts.stage = 'haiku'
            WHERE listings.status IN ('haiku_yes', 'haiku_maybe')
            """
        ).fetchall()
        pending_count = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE status LIKE 'haiku_%'"
        ).fetchone()[0]

        for row in rows:
            assessment = await assess_listing(row, profile, feedback_context)
            bucket = assessment.bucket()
            conn.execute(
                "UPDATE listings SET status = ? WHERE id = ?",
                (f"sonnet_{bucket}", row["id"]),
            )
            db.log_verdict(
                conn,
                listing_id=row["id"],
                stage=STAGE,
                verdict=str(assessment.score),
                reason=assessment.rationale,
                detail_json=json.dumps(
                    {
                        "score": assessment.score,
                        "matched_criteria": assessment.matched_criteria,
                        "concerns": assessment.concerns,
                        "rationale": assessment.rationale,
                    }
                ),
            )
            db.log_cost(
                conn,
                stage=f"fit:{STAGE}",
                model=MODEL,
                num_turns=assessment.num_turns,
                cost_usd=assessment.cost_usd,
                detail=row["title"],
            )
            total_cost += assessment.cost_usd
            scored += 1
            print(f"[{assessment.score:3}/{bucket:8}] {row['title'][:55]}")
            for c in assessment.matched_criteria:
                print(f"    + {c}")
            for c in assessment.concerns:
                print(f"    ? {c}")

    print(f"\nScored {scored} listing(s) with Sonnet. (${total_cost:.4f} total cost)")
    if scored:
        per_item = total_cost / scored
        projected_all = per_item * pending_count
        saved = projected_all - total_cost
        skipped = pending_count - scored
        print(
            f"Haiku screened out {skipped} of {pending_count} pre-filtered listing(s) as 'no', "
            f"so Sonnet only scored {scored}. Estimated cost if Sonnet had scored all "
            f"{pending_count} instead: ${projected_all:.4f} - roughly ${saved:.4f} saved by "
            f"tiering models."
        )


def main() -> None:
    asyncio.run(run_sonnet_pass())


if __name__ == "__main__":
    main()
