"""Detailed fit judgement: Sonnet reads a listing, the user's profile, and Haiku's coarse
verdict, then gives a scored, itemised assessment. Only runs on what Haiku's coarse pass (Phase
6) didn't rule out - the whole point of model tiering is that the pricier model only ever sees
the subset worth a careful look.

Runs as one Anthropic Message Batches API call (Phase 12) rather than one query per listing - see
`fit/haiku.py`'s docstring for why (50% cheaper, plain `anthropic` SDK, shared CV/criteria/
feedback block cached in `system` rather than repeated per listing).

Run with: uv run python -m job_search_agent.fit.sonnet
"""

import asyncio
import json
import sqlite3
from dataclasses import dataclass, field

from job_search_agent import db, limits
from job_search_agent.fit.batch_client import BatchResult, run_batch
from job_search_agent.profile import Profile, feedback_examples_context, load_profile
from job_search_agent.pricing import estimate_cost_usd

MODEL = "claude-sonnet-5"
STAGE = "sonnet"
MAX_OUTPUT_TOKENS = 1024

ASSESSMENT_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "score": {"type": "integer"},
            "matched_criteria": {"type": "array", "items": {"type": "string"}},
            "concerns": {"type": "array", "items": {"type": "string"}},
            "rationale": {"type": "string"},
        },
        "required": ["score", "matched_criteria", "concerns", "rationale"],
        "additionalProperties": False,
    },
}


@dataclass
class Assessment:
    score: int = 0
    matched_criteria: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    rationale: str = "No response"
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0

    def bucket(self) -> str:
        if self.score >= 70:
            return "strong"
        if self.score >= 40:
            return "possible"
        return "weak"


def build_system_prompt(profile: Profile, feedback_context: str) -> str:
    feedback_block = f"\n\n{feedback_context}" if feedback_context else ""
    return f"{profile.as_prompt_context()}{feedback_block}"


def build_user_message(listing: sqlite3.Row) -> str:
    return (
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


def _batch_request(listing: sqlite3.Row, system_text: str) -> dict:
    return {
        "custom_id": f"listing-{listing['id']}",
        "params": {
            "model": MODEL,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "system": [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": build_user_message(listing)}],
            "output_config": {"format": ASSESSMENT_SCHEMA},
        },
    }


def _parse_result(result: BatchResult) -> Assessment:
    text = next(b.text for b in result.message.content if b.type == "text")
    out = json.loads(text)
    usage = result.message.usage
    cost_usd = estimate_cost_usd(
        MODEL,
        usage.input_tokens,
        usage.output_tokens,
        cache_creation_input_tokens=usage.cache_creation_input_tokens or 0,
        cache_read_input_tokens=usage.cache_read_input_tokens or 0,
    )
    return Assessment(
        # The raw Messages API's structured-output schema doesn't support integer min/max (unlike
        # claude-agent-sdk's output_format, which tolerated it) - the 0-100 range is prompted for
        # but not schema-enforced, so clamp defensively rather than trust the model never drifts.
        score=max(0, min(100, out.get("score", 0))),
        matched_criteria=out.get("matched_criteria", []),
        concerns=out.get("concerns", []),
        rationale=out.get("rationale", "No response"),
        cost_usd=cost_usd,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
    )


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
        if not rows:
            print("No listings pending a Sonnet pass.")
            return
        rows = limits.cap_listings(rows, stage=STAGE)

        system_text = build_system_prompt(profile, feedback_context)
        user_texts = [build_user_message(row) for row in rows]
        limits.check_spend_cap(MODEL, system_text, user_texts, MAX_OUTPUT_TOKENS)

        requests = [_batch_request(row, system_text) for row in rows]
        results = await run_batch(requests)

        for row in rows:
            result = results.get(f"listing-{row['id']}")
            if result is None or not result.succeeded:
                reason = result.error if result else "missing from batch results"
                db.log_event(
                    conn, stage=STAGE, message=f"Batch request failed: {reason}", listing_id=row["id"]
                )
                conn.commit()
                print(f"[error] {row['title'][:55]} - batch request {reason}")
                continue

            assessment = _parse_result(result)
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
                num_turns=1,
                cost_usd=assessment.cost_usd,
                detail=row["title"],
                input_tokens=assessment.input_tokens,
                output_tokens=assessment.output_tokens,
            )
            conn.commit()
            total_cost += assessment.cost_usd
            scored += 1
            print(f"[{assessment.score:3}/{bucket:8}] {row['title'][:55]}")
            for c in assessment.matched_criteria:
                print(f"    + {c}")
            for c in assessment.concerns:
                print(f"    ? {c}")

    print(f"\nScored {scored} listing(s) with Sonnet. (${total_cost:.4f} total cost, batch)")
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
