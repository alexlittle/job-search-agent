"""Validation/retry loop for Sonnet's "uncertain" verdicts (Phase 14).

Sonnet's structured output (fit/sonnet.py) includes an `uncertain` flag - true when a listing's
own description was too thin to judge confidently (a short teaser with no real specifics, common
on some RSS feeds and Adzuna results). Rather than have a low-information guess look as confident
as a well-informed one, those listings land in an intermediate 'sonnet_uncertain' status instead
of a normal strong/possible/weak bucket (see webapp/results.py's PENDING_WHERE). This module gives
each of them exactly one shot at a better answer: fetch the full posting page (plain HTTP, no LLM
cost) and re-run the same Sonnet assessment with that fuller text.

Each listing gets retried at most once, ever, by construction: regardless of outcome (resolved,
still uncertain, or the page couldn't even be fetched), status always moves out of
'sonnet_uncertain' before this function returns for that listing, so the next run's query for
'sonnet_uncertain' listings won't pick it up again. The one exception is a batch-level failure
(a transient API error, not a content judgement) - that leaves status unchanged, matching how
fit/haiku.py and fit/sonnet.py already treat a failed batch request as "try again next run", not
as one of this listing's real chances.

A page that can't be fetched at all skips the Sonnet call entirely (no point paying for a
re-assessment with no new information) and finalizes immediately from the original score, with the
outcome ("uncertain, page unreachable") recorded explicitly rather than silently kept identical to
a confident verdict - see detail_json's "uncertain"/"page_fetched" fields, shown on the dashboard
via _listing_detail.html.

Uses the same MAX_LISTINGS_PER_RUN/MAX_SPEND_PER_RUN_USD guards (Phase 12) as Haiku/Sonnet, since
a successful retry is one more paid Sonnet call per listing.

Run with: uv run python -m job_search_agent.fit.retry
"""

import asyncio
import json
import sqlite3

import requests
from bs4 import BeautifulSoup

from job_search_agent import db, limits
from job_search_agent.fit import sonnet
from job_search_agent.fit.batch_client import run_batch
from job_search_agent.profile import feedback_examples_context, load_profile
from job_search_agent.user_agent import build_user_agent

STAGE = "sonnet_retry"
FETCH_TIMEOUT_SECONDS = 15
# Generous enough to capture a real job description, bounded so one huge page can't blow out the
# prompt (or the retry's cost) - see the module docstring on why this whole pass needs its own
# spend guard anyway.
MAX_PAGE_TEXT_CHARS = 6000


def fetch_full_description(url: str) -> str | None:
    """Best-effort fetch of the full posting page's visible text. Returns None on any failure
    (network error, non-2xx, unparseable content) rather than raising - a page that can't be
    fetched just means this listing finalizes on its original best-guess score, not a pipeline
    crash."""
    try:
        response = requests.get(
            url, headers={"User-Agent": build_user_agent()}, timeout=FETCH_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except requests.RequestException:
        return None
    soup = BeautifulSoup(response.content, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    text = " ".join(soup.get_text(separator=" ").split())
    return text[:MAX_PAGE_TEXT_CHARS] if text else None


def build_retry_message(listing: sqlite3.Row, full_text: str) -> str:
    return (
        "## Listing to re-evaluate (retry with the full posting page)\n"
        f"Title: {listing['title']}\n"
        f"Company: {listing['company']}\n"
        f"Location: {listing['location']}\n\n"
        "## Original (thin) description\n"
        f"{listing['description']}\n\n"
        "## Full posting page text (freshly fetched - may include some site navigation/footer "
        "noise around the actual job details)\n"
        f"{full_text}\n\n"
        "You previously marked this listing 'uncertain' because the original description didn't "
        "give you enough to judge confidently. Re-assess using the fuller text above.\n"
        "- score: 0-100, where 100 is an ideal match given the candidate's CV and criteria above\n"
        "- matched_criteria / concerns / rationale: as before, updated for what you can now see\n"
        "- uncertain: true only if even this fuller text still isn't enough to judge confidently "
        "(e.g. the page didn't actually contain real job details) - say so honestly rather than "
        "guess; false if the fuller text resolved it"
    )


def _finalize_unfetchable(conn: sqlite3.Connection, row: sqlite3.Row) -> None:
    original = json.loads(row["sonnet_detail_json"])
    bucket = sonnet.bucket_for_score(original["score"])
    conn.execute(
        "UPDATE listings SET status = ? WHERE id = ?", (f"sonnet_{bucket}", row["id"])
    )
    db.log_verdict(
        conn,
        listing_id=row["id"],
        stage="sonnet",
        verdict=str(original["score"]),
        reason="Could not fetch the full posting page on retry - kept the original best-guess score.",
        detail_json=json.dumps({**original, "uncertain": True, "page_fetched": False}),
    )
    conn.commit()


async def run_retry_pass() -> None:
    profile = load_profile()
    total_cost = 0.0
    resolved = 0
    still_uncertain = 0
    unreachable = 0

    with db.connect() as conn:
        feedback_context = feedback_examples_context(conn)
        rows = conn.execute(
            """
            SELECT listings.*, verdicts.detail_json AS sonnet_detail_json
            FROM listings
            JOIN verdicts ON verdicts.listing_id = listings.id AND verdicts.stage = 'sonnet'
            WHERE listings.status = 'sonnet_uncertain'
            """
        ).fetchall()
        if not rows:
            print("No uncertain listings pending retry.")
            return
        rows = limits.cap_listings(rows, stage=STAGE)

        page_texts = {row["id"]: fetch_full_description(row["url"]) for row in rows}
        to_retry = [row for row in rows if page_texts[row["id"]]]
        unfetchable = [row for row in rows if not page_texts[row["id"]]]

        for row in unfetchable:
            _finalize_unfetchable(conn, row)
            unreachable += 1
            print(f"[unresolved] {row['title'][:55]} - couldn't fetch {row['url']}")

        if not to_retry:
            print(
                f"\nRetry pass: {unreachable} listing(s) stayed uncertain (page unreachable), "
                "0 re-scored."
            )
            return

        system_text = sonnet.build_system_prompt(profile, feedback_context)
        user_messages = {row["id"]: build_retry_message(row, page_texts[row["id"]]) for row in to_retry}
        limits.check_spend_cap(
            sonnet.MODEL, system_text, list(user_messages.values()), sonnet.MAX_OUTPUT_TOKENS
        )

        requests_payload = [
            sonnet._batch_request(row, system_text, user_message=user_messages[row["id"]])
            for row in to_retry
        ]
        results = await run_batch(requests_payload)

        for row in to_retry:
            result = results.get(f"listing-{row['id']}")
            if result is None or not result.succeeded:
                reason = result.error if result else "missing from batch results"
                db.log_event(
                    conn,
                    stage=STAGE,
                    message=f"Retry batch request failed: {reason} - left uncertain for next run",
                    listing_id=row["id"],
                )
                conn.commit()
                print(f"[error] {row['title'][:55]} - retry batch request {reason}")
                continue

            assessment = sonnet._parse_result(result)
            bucket = assessment.bucket()
            conn.execute(
                "UPDATE listings SET status = ? WHERE id = ?", (f"sonnet_{bucket}", row["id"])
            )
            db.log_verdict(
                conn,
                listing_id=row["id"],
                stage="sonnet",
                verdict=str(assessment.score),
                reason=assessment.rationale,
                detail_json=json.dumps(
                    {
                        "score": assessment.score,
                        "matched_criteria": assessment.matched_criteria,
                        "concerns": assessment.concerns,
                        "rationale": assessment.rationale,
                        "uncertain": assessment.uncertain,
                        "page_fetched": True,
                    }
                ),
            )
            db.log_cost(
                conn,
                stage=f"fit:{STAGE}",
                model=sonnet.MODEL,
                num_turns=1,
                cost_usd=assessment.cost_usd,
                detail=row["title"],
                input_tokens=assessment.input_tokens,
                output_tokens=assessment.output_tokens,
            )
            conn.commit()
            total_cost += assessment.cost_usd
            if assessment.uncertain:
                still_uncertain += 1
                print(f"[still uncertain, {assessment.score:3}/{bucket:8}] {row['title'][:55]}")
            else:
                resolved += 1
                print(f"[resolved,       {assessment.score:3}/{bucket:8}] {row['title'][:55]}")

    print(
        f"\nRetry pass: {resolved} resolved, {still_uncertain} still uncertain after reading the "
        f"full page, {unreachable} unresolved (page unreachable). (${total_cost:.4f} total cost, "
        "batch)"
    )


def main() -> None:
    asyncio.run(run_retry_pass())


if __name__ == "__main__":
    main()
