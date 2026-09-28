"""Shared plumbing for running fit-agent calls through the Anthropic Message Batches API - 50%
cheaper than synchronous calls for the same requests (Phase 12). Uses the plain `anthropic` SDK
directly, since `claude-agent-sdk` is built around synchronous tool-use loops (`query()`) and
doesn't expose batch submission.

A batch keeps running on Anthropic's side once submitted, regardless of whether this process
stays connected to poll it - so a dropped connection (a laptop's wifi, going to sleep mid-run)
while waiting on a batch shouldn't lose track of it and quietly resubmit (re-paying for) the
same requests next run. `run_or_resume_batch` is the resilient entry point fit/haiku.py,
fit/sonnet.py, and fit/retry.py all use for this: it persists the batch id to the DB the moment
it's submitted (via db.get_setting/set_setting, no schema change needed), and on the next call
(whether that's later in the same run or a whole new scheduled run), resumes waiting on it
instead of building a new one - see its docstring for the exact protocol.
"""

import asyncio
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from anthropic import AsyncAnthropic

from job_search_agent import db
from job_search_agent.claude_client import require_api_key

POLL_INTERVAL_SECONDS = 10
# Anthropic gives a batch up to 24h to complete, but small batches like this project's (tens of
# requests) typically finish in well under a minute. Capped rather than unbounded so a stuck batch
# can't hang a pipeline run forever - if this is hit, the batch id is in the error so it can be
# checked later (client.messages.batches.retrieve(<id>)) instead of losing track of it.
MAX_POLL_SECONDS = 1800


@dataclass
class BatchResult:
    custom_id: str
    succeeded: bool
    message: Any | None = None  # anthropic.types.Message, when succeeded
    error: str | None = None


@dataclass
class BatchRunOutcome:
    rows: list[sqlite3.Row]
    results: dict[str, BatchResult]


class BatchInterrupted(Exception):
    """Raised when a submitted batch can't be waited on to completion right now - a dropped
    connection while polling, or MAX_POLL_SECONDS being hit. Either way the batch itself is
    unaffected (still running, or already billed, on Anthropic's side); `batch_id` is included
    so the caller can leave it recorded for the next run to pick back up rather than losing
    track of it."""

    def __init__(self, batch_id: str, detail: str):
        super().__init__(f"Batch {batch_id} not resolved: {detail}")
        self.batch_id = batch_id


def _client() -> AsyncAnthropic:
    return AsyncAnthropic(api_key=require_api_key())


async def submit_batch(requests: list[dict]) -> str:
    """Submits `requests` and returns the new batch's id immediately, before any polling -
    callers should persist this right away so an interrupted poll never loses track of an
    already-submitted (and already billed) batch."""
    client = _client()
    batch = await client.messages.batches.create(requests=requests)
    print(f"Submitted batch {batch.id} ({len(requests)} request(s)), waiting for it to finish...")
    return batch.id


async def wait_for_batch(batch_id: str) -> dict[str, BatchResult]:
    """Polls an existing batch (freshly submitted, or left over from an earlier interrupted run)
    until it ends, then decodes its results. Raises BatchInterrupted - never lets a plain
    connection error or the poll timeout propagate as-is - so callers have one exception type to
    catch and a batch id to hold onto either way."""
    client = _client()
    waited = 0
    try:
        batch = await client.messages.batches.retrieve(batch_id)
        while batch.processing_status != "ended":
            if waited >= MAX_POLL_SECONDS:
                raise TimeoutError(f"still {batch.processing_status!r} after {MAX_POLL_SECONDS}s")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            waited += POLL_INTERVAL_SECONDS
            batch = await client.messages.batches.retrieve(batch_id)
    except Exception as exc:
        raise BatchInterrupted(batch_id, str(exc)) from exc

    results: dict[str, BatchResult] = {}
    decoder = await client.messages.batches.results(batch_id)
    async for entry in decoder:
        if entry.result.type == "succeeded":
            results[entry.custom_id] = BatchResult(entry.custom_id, True, message=entry.result.message)
        else:
            results[entry.custom_id] = BatchResult(entry.custom_id, False, error=entry.result.type)
    return results


async def run_batch(requests: list[dict]) -> dict[str, BatchResult]:
    """Submits `requests` and blocks until every request has a result. The original all-in-one
    entry point; prefer `run_or_resume_batch` for anything that should survive a dropped
    connection across runs."""
    batch_id = await submit_batch(requests)
    return await wait_for_batch(batch_id)


async def run_or_resume_batch(
    conn: sqlite3.Connection,
    pending_key: str,
    prepare: Callable[[], tuple[list[sqlite3.Row], list[dict]] | None],
) -> BatchRunOutcome | None:
    """The resilient submit/poll/decode flow one fit-agent stage uses per run.

    First checks `pending_key` (a `settings` table row, JSON: {batch_id, listing_ids}) for a
    batch left over from a previous run that got interrupted mid-poll. If there is one, resumes
    waiting on *that* instead of calling `prepare()` at all - so the listings it covers can't
    get bundled into a second, duplicate (and separately billed) batch while the first one is
    still quietly finishing on Anthropic's side.

    Otherwise calls `prepare()` - which should do everything up to building the batch's request
    payloads (querying which listings are due, capping/spend-checking them) - and, if it returns
    requests, submits them and persists the new batch id before polling.

    Returns None when there's nothing to report this run (nothing due, or a leftover batch still
    isn't done) - the caller should just return; this picks back up next run either way. When it
    returns a result, `outcome.rows` are the actual listing rows to process (re-fetched by id
    when resuming, since the original Row objects from the run that submitted them are long
    gone) and `outcome.results` are keyed the same way normal per-listing lookups already expect
    (`f"listing-{row['id']}"`).
    """
    pending_raw = db.get_setting(conn, pending_key)
    if pending_raw:
        pending = json.loads(pending_raw)
        batch_id = pending["batch_id"]
        listing_ids = pending["listing_ids"]
        print(f"Resuming batch {batch_id} left over from a previous interrupted run...")
        try:
            results = await wait_for_batch(batch_id)
        except BatchInterrupted as exc:
            print(f"[warn] {exc} - leaving it recorded, will try again next run.")
            return None
        db.set_setting(conn, pending_key, "")
        conn.commit()
        placeholders = ",".join("?" * len(listing_ids))
        rows = conn.execute(
            f"SELECT * FROM listings WHERE id IN ({placeholders})", listing_ids
        ).fetchall()
        return BatchRunOutcome(rows=rows, results=results)

    prepared = prepare()
    if prepared is None:
        return None
    rows, requests = prepared

    batch_id = await submit_batch(requests)
    db.set_setting(
        conn,
        pending_key,
        json.dumps({"batch_id": batch_id, "listing_ids": [row["id"] for row in rows]}),
    )
    conn.commit()

    try:
        results = await wait_for_batch(batch_id)
    except BatchInterrupted as exc:
        print(f"[warn] {exc} - batch id saved, will pick up its results next run.")
        return None

    db.set_setting(conn, pending_key, "")
    conn.commit()
    return BatchRunOutcome(rows=rows, results=results)
