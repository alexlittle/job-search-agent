"""Coarse fit judgement: Haiku reads one listing plus the user's profile and gives a quick
yes/maybe/no verdict with a one-line reason. Deliberately cheap and fast - Sonnet (Phase 7) only
looks at what this stage doesn't rule out, so a wrong "no" here is costly (the listing never gets
a proper look) while a wrong "yes"/"maybe" just costs a bit of Sonnet budget later. The prompt
reflects that asymmetry explicitly.

Runs as one Anthropic Message Batches API call (Phase 12) rather than one query per listing - 50%
cheaper for the same requests, via the plain `anthropic` SDK (see `fit/batch_client.py`) rather
than `claude-agent-sdk`, which doesn't expose batch submission. The CV/criteria/feedback block is
identical for every listing in a run, so it goes in `system` with a prompt-caching breakpoint
rather than being repeated in each listing's own message.

Run with: uv run python -m job_search_agent.fit.haiku
"""

import asyncio
import json
import sqlite3

from job_search_agent import db, limits
from job_search_agent.fit.batch_client import BatchResult, run_batch
from job_search_agent.profile import Profile, feedback_examples_context, load_profile
from job_search_agent.pricing import estimate_cost_usd

MODEL = "claude-haiku-4-5-20251001"
STAGE = "haiku"
MAX_OUTPUT_TOKENS = 300

VERDICT_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["yes", "maybe", "no"]},
            "reason": {"type": "string"},
        },
        "required": ["verdict", "reason"],
        "additionalProperties": False,
    },
}


def build_system_prompt(profile: Profile, feedback_context: str) -> str:
    feedback_block = f"\n\n{feedback_context}" if feedback_context else ""
    return f"{profile.as_prompt_context()}{feedback_block}"


def build_user_message(listing: sqlite3.Row) -> str:
    return (
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


def _batch_request(listing: sqlite3.Row, system_text: str) -> dict:
    return {
        "custom_id": f"listing-{listing['id']}",
        "params": {
            "model": MODEL,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "system": [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": build_user_message(listing)}],
            "output_config": {"format": VERDICT_SCHEMA},
        },
    }


def _parse_result(result: BatchResult) -> tuple[str, str, float, int, int]:
    text = next(b.text for b in result.message.content if b.type == "text")
    parsed = json.loads(text)
    verdict = parsed.get("verdict", "no")
    reason = parsed.get("reason", "No response")
    usage = result.message.usage
    cost_usd = estimate_cost_usd(
        MODEL,
        usage.input_tokens,
        usage.output_tokens,
        cache_creation_input_tokens=usage.cache_creation_input_tokens or 0,
        cache_read_input_tokens=usage.cache_read_input_tokens or 0,
    )
    return verdict, reason, cost_usd, usage.input_tokens, usage.output_tokens


async def run_haiku_pass() -> None:
    profile = load_profile()
    total_cost = 0.0
    counts = {"yes": 0, "maybe": 0, "no": 0}

    with db.connect() as conn:
        feedback_context = feedback_examples_context(conn)
        rows = conn.execute("SELECT * FROM listings WHERE status = 'pending_fit'").fetchall()
        if not rows:
            print("No listings pending a Haiku pass.")
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
                print(f"[error] {row['title'][:60]} - batch request {reason}")
                continue

            verdict, reason, cost_usd, in_tok, out_tok = _parse_result(result)
            conn.execute(
                "UPDATE listings SET status = ? WHERE id = ?",
                (f"haiku_{verdict}", row["id"]),
            )
            db.log_verdict(conn, listing_id=row["id"], stage=STAGE, verdict=verdict, reason=reason)
            db.log_cost(
                conn,
                stage=f"fit:{STAGE}",
                model=MODEL,
                num_turns=1,
                cost_usd=cost_usd,
                detail=row["title"],
                input_tokens=in_tok,
                output_tokens=out_tok,
            )
            conn.commit()
            total_cost += cost_usd
            counts[verdict] = counts.get(verdict, 0) + 1
            print(f"[{verdict:>5}] {row['title'][:60]} - {reason}")

    print(
        f"\nScored {sum(counts.values())} listing(s): "
        f"{counts['yes']} yes, {counts['maybe']} maybe, {counts['no']} no. "
        f"(${total_cost:.4f} total cost, batch)"
    )


def main() -> None:
    asyncio.run(run_haiku_pass())


if __name__ == "__main__":
    main()
