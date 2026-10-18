"""Detailed fit judgement: Sonnet reads a listing, the user's profile, and Haiku's coarse
verdict, then gives a scored, itemised assessment. Only runs on what Haiku's coarse pass (Phase
6) didn't rule out - the whole point of model tiering is that the pricier model only ever sees
the subset worth a careful look (still true under Claude Code auth too, even without a $ saving -
see fit/haiku.py's docstring on why tiering stays either way).

Two transports, chosen by `claude_client.auth_mode()` - see `fit/haiku.py`'s docstring for the
full explanation (50% cheaper Batches API in "api" mode via the plain `anthropic` SDK, one
`claude-agent-sdk` query per listing in "claude_code" mode).

Run with: uv run python -m job_search_agent.fit.sonnet
"""

import asyncio
import json
import sqlite3
from dataclasses import dataclass, field

from job_search_agent import db, limits
from job_search_agent.claude_client import auth_mode
from job_search_agent.fit import sdk_calls
from job_search_agent.fit.batch_client import BatchResult, run_or_resume_batch
from job_search_agent.fit.results import ListingResult
from job_search_agent.profile import Profile, feedback_examples_context, load_profile
from job_search_agent.pricing import estimate_cost_usd

MODEL = "claude-sonnet-5"
STAGE = "sonnet"
# Was 1024 - real-world testing (2026-09-28) found ~40% of real responses (score +
# matched_criteria + concerns + rationale) were truncated mid-JSON at that cap, wasting the
# whole request (unusable output, still billed, then needs a retry-pass call on top). Only
# actually enforced in "api" mode's Batches request - claude-agent-sdk (fit/sdk_calls.py,
# "claude_code" mode) has no equivalent per-response token cap to pass at all, so this constant
# only affects the spend-cap estimate there, not a real limit.
MAX_OUTPUT_TOKENS = 2048
PENDING_BATCH_KEY = "pending_batch:sonnet"

ASSESSMENT_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "score": {"type": "integer"},
            "matched_criteria": {"type": "array", "items": {"type": "string"}},
            "concerns": {"type": "array", "items": {"type": "string"}},
            "rationale": {"type": "string"},
            "uncertain": {"type": "boolean"},
        },
        "required": ["score", "matched_criteria", "concerns", "rationale", "uncertain"],
        "additionalProperties": False,
    },
}


def bucket_for_score(score: int) -> str:
    if score >= 70:
        return "strong"
    if score >= 40:
        return "possible"
    return "weak"


@dataclass
class Assessment:
    score: int = 0
    matched_criteria: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    rationale: str = "No response"
    uncertain: bool = False
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0

    def bucket(self) -> str:
        return bucket_for_score(self.score)


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
        "- rationale: a short paragraph explaining the score\n"
        "- uncertain: true if the description above is too thin to judge confidently (a short "
        "teaser with no real specifics, for example) - still give your best-guess score either "
        "way, just flag it honestly rather than let a low-information guess look as confident as "
        "a well-informed one. false if the description gave you enough to judge properly."
    )


def _batch_request(listing: sqlite3.Row, system_text: str, user_message: str | None = None) -> dict:
    return {
        "custom_id": f"listing-{listing['id']}",
        "params": {
            "model": MODEL,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "system": [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user_message or build_user_message(listing)}],
            "output_config": {"format": ASSESSMENT_SCHEMA},
        },
    }


def _from_batch_result(result: BatchResult) -> ListingResult:
    if not result.succeeded:
        return ListingResult(succeeded=False, error=result.error)
    text = next(b.text for b in result.message.content if b.type == "text")
    usage = result.message.usage
    cost_usd = estimate_cost_usd(
        MODEL,
        usage.input_tokens,
        usage.output_tokens,
        cache_creation_input_tokens=usage.cache_creation_input_tokens or 0,
        cache_read_input_tokens=usage.cache_read_input_tokens or 0,
    )
    return ListingResult(
        succeeded=True,
        raw_json=text,
        cost_usd=cost_usd,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
    )


def _parse_result(result: ListingResult) -> Assessment:
    out = json.loads(result.raw_json)
    return Assessment(
        # The raw Messages API's structured-output schema doesn't support integer min/max (unlike
        # claude-agent-sdk's output_format, which tolerated it) - the 0-100 range is prompted for
        # but not schema-enforced, so clamp defensively rather than trust the model never drifts.
        score=max(0, min(100, out.get("score", 0))),
        matched_criteria=out.get("matched_criteria", []),
        concerns=out.get("concerns", []),
        rationale=out.get("rationale", "No response"),
        uncertain=bool(out.get("uncertain", False)),
        cost_usd=result.cost_usd,
        input_tokens=result.input_tokens or 0,
        output_tokens=result.output_tokens or 0,
    )


def _due_rows(conn) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT listings.*, verdicts.verdict AS haiku_verdict, verdicts.reason AS haiku_reason
        FROM listings
        JOIN verdicts ON verdicts.listing_id = listings.id AND verdicts.stage = 'haiku'
        WHERE listings.status IN ('haiku_yes', 'haiku_maybe')
        """
    ).fetchall()


async def _score_via_batch(
    conn, system_text: str
) -> tuple[list[sqlite3.Row], dict[str, ListingResult]] | None:
    def _prepare() -> tuple[list[sqlite3.Row], list[dict]] | None:
        rows = _due_rows(conn)
        if not rows:
            print("No listings pending a Sonnet pass.")
            return None
        rows = limits.cap_listings(rows, stage=STAGE)
        user_texts = [build_user_message(row) for row in rows]
        limits.check_spend_cap(MODEL, system_text, user_texts, MAX_OUTPUT_TOKENS, batch=True)
        return rows, [_batch_request(row, system_text) for row in rows]

    outcome = await run_or_resume_batch(conn, PENDING_BATCH_KEY, _prepare)
    if outcome is None:
        return None
    return outcome.rows, {cid: _from_batch_result(r) for cid, r in outcome.results.items()}


async def _score_via_claude_code(
    conn, system_text: str
) -> tuple[list[sqlite3.Row], dict[str, ListingResult]] | None:
    rows = _due_rows(conn)
    if not rows:
        print("No listings pending a Sonnet pass.")
        return None
    rows = limits.cap_listings(rows, stage=STAGE)
    user_texts = [build_user_message(row) for row in rows]
    limits.check_spend_cap(MODEL, system_text, user_texts, MAX_OUTPUT_TOKENS, batch=False)

    results: dict[str, ListingResult] = {}
    for row in rows:
        results[f"listing-{row['id']}"] = await sdk_calls.run_single(
            MODEL, system_text, build_user_message(row), ASSESSMENT_SCHEMA
        )
    return rows, results


async def run_sonnet_pass() -> None:
    profile = load_profile()
    total_cost = 0.0
    scored = 0
    mode = auth_mode()

    with db.connect() as conn:
        feedback_context = feedback_examples_context(conn)
        system_text = build_system_prompt(profile, feedback_context)
        # Informational only (the cost-comparison print at the end) - computed unconditionally
        # so it's still accurate whether this run resumes a leftover batch or submits a fresh one.
        pending_count = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE status LIKE 'haiku_%'"
        ).fetchone()[0]

        outcome = (
            await _score_via_claude_code(conn, system_text)
            if mode == "claude_code"
            else await _score_via_batch(conn, system_text)
        )
        if outcome is None:
            return
        rows, results = outcome

        for row in rows:
            result = results.get(f"listing-{row['id']}")
            if result is None or not result.succeeded:
                reason = result.error if result else "missing result"
                db.log_event(
                    conn, stage=STAGE, message=f"Request failed: {reason}", listing_id=row["id"]
                )
                conn.commit()
                print(f"[error] {row['title'][:55]} - {reason}")
                continue

            try:
                assessment = _parse_result(result)
            except json.JSONDecodeError as exc:
                # A response cut off mid-JSON (hit MAX_OUTPUT_TOKENS before finishing) - a real,
                # not-rare failure mode found in live testing (2026-09-28, ~40% of one batch).
                # Treat it the same as any other failed request: log it and leave the listing
                # for next run, rather than letting json.loads() crash this whole pass.
                db.log_event(
                    conn,
                    stage=STAGE,
                    message=f"Response truncated/unparseable: {exc}",
                    listing_id=row["id"],
                )
                conn.commit()
                print(f"[error] {row['title'][:55]} - truncated/unparseable response")
                continue
            bucket = assessment.bucket()
            # An "uncertain" verdict (Phase 14: description too thin to judge confidently) is
            # left in an intermediate status rather than a normal strong/possible/weak bucket, so
            # fit/retry.py can find it and give it one shot at a fuller description (the full
            # posting page) before it's finalized either way - see PENDING_WHERE in
            # webapp/results.py, which treats this the same as any other "not fully assessed yet"
            # status.
            new_status = "sonnet_uncertain" if assessment.uncertain else f"sonnet_{bucket}"
            conn.execute(
                "UPDATE listings SET status = ? WHERE id = ?",
                (new_status, row["id"]),
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
                        "uncertain": assessment.uncertain,
                        "page_fetched": False,
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
            tag = "uncertain" if assessment.uncertain else bucket
            print(f"[{assessment.score:3}/{tag:9}] {row['title'][:55]}")
            for c in assessment.matched_criteria:
                print(f"    + {c}")
            for c in assessment.concerns:
                print(f"    ? {c}")

    label = "estimated cost, not billed" if mode == "claude_code" else "total cost, batch"
    print(f"\nScored {scored} listing(s) with Sonnet. (${total_cost:.4f} {label})")
    if scored:
        per_item = total_cost / scored
        projected_all = per_item * pending_count
        saved = projected_all - total_cost
        skipped = pending_count - scored
        saving_note = (
            "fewer, cheaper session calls" if mode == "claude_code" else f"${saved:.4f} saved"
        )
        print(
            f"Haiku screened out {skipped} of {pending_count} pre-filtered listing(s) as 'no', "
            f"so Sonnet only scored {scored}. Estimated cost if Sonnet had scored all "
            f"{pending_count} instead: ${projected_all:.4f} - roughly {saving_note} by tiering "
            "models."
        )


def main() -> None:
    asyncio.run(run_sonnet_pass())


if __name__ == "__main__":
    main()
