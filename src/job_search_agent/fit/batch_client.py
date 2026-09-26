"""Shared plumbing for running fit-agent calls through the Anthropic Message Batches API - 50%
cheaper than synchronous calls for the same requests (Phase 12). Uses the plain `anthropic` SDK
directly, since `claude-agent-sdk` is built around synchronous tool-use loops (`query()`) and
doesn't expose batch submission.
"""

import asyncio
from dataclasses import dataclass
from typing import Any

from anthropic import AsyncAnthropic

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


def _client() -> AsyncAnthropic:
    return AsyncAnthropic(api_key=require_api_key())


async def run_batch(requests: list[dict]) -> dict[str, BatchResult]:
    """Submits `requests` (already in Batches API {custom_id, params} shape), blocks until every
    request in the batch has a result, and returns {custom_id: BatchResult}."""
    client = _client()
    batch = await client.messages.batches.create(requests=requests)
    print(f"Submitted batch {batch.id} ({len(requests)} request(s)), waiting for it to finish...")

    waited = 0
    while batch.processing_status != "ended":
        if waited >= MAX_POLL_SECONDS:
            raise TimeoutError(
                f"Batch {batch.id} still {batch.processing_status!r} after {MAX_POLL_SECONDS}s - "
                "giving up waiting here, but it's still running on Anthropic's side; check "
                f"client.messages.batches.retrieve({batch.id!r}) later for its results."
            )
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        waited += POLL_INTERVAL_SECONDS
        batch = await client.messages.batches.retrieve(batch.id)

    results: dict[str, BatchResult] = {}
    decoder = await client.messages.batches.results(batch.id)
    async for entry in decoder:
        if entry.result.type == "succeeded":
            results[entry.custom_id] = BatchResult(entry.custom_id, True, message=entry.result.message)
        else:
            results[entry.custom_id] = BatchResult(entry.custom_id, False, error=entry.result.type)
    return results
