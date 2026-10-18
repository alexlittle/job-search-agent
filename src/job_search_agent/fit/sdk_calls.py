"""Per-listing claude-agent-sdk transport for the fit-agent stages, used only in "claude_code"
auth mode (see claude_client.py's module docstring) - the Batches API (fit/batch_client.py) has
no ambient-auth equivalent, so this is the fallback: one ordinary claude-agent-sdk query() per
listing instead of one batch covering all of them. Loses the Batches API's 50% discount and
prompt caching, but neither matters once nothing here is metered - see
limits.check_spend_cap's `batch` parameter. Costs more real session usage per listing than the
per-token numbers alone suggest, though: even a trivial call carries Claude Code's own framework
overhead (~7-8k cache-creation tokens in real testing), not just this project's own prompt.

No resume-safety mechanism here (unlike fit/batch_client.run_or_resume_batch) - there's nothing
in flight to lose track of if a listing's call is interrupted, since each listing is independent
and gets committed to the DB right after it resolves (see fit/haiku.py etc.'s per-row loop); a
dropped connection partway through just leaves whatever hasn't been reached yet for next run,
same as every other stage in this pipeline.
"""

import json

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKError, ResultMessage, query

from job_search_agent.claude_client import call_with_retry, sdk_env
from job_search_agent.fit.results import ListingResult


async def run_single(model: str, system_text: str, user_message: str, schema: dict) -> ListingResult:
    """Runs one query() call for one listing, retried once on a transient SDK error (see
    claude_client.call_with_retry) - there's no batch to fall back into here, so each listing
    needs its own retry. Returns a failed ListingResult rather than raising on any failure, so
    the caller's per-listing loop can log it and move on exactly like a failed batch request
    does today."""
    options = ClaudeAgentOptions(
        model=model,
        max_turns=1,
        tools=[],
        system_prompt=system_text,
        output_format=schema,
        env=sdk_env(),
    )

    async def _call() -> ResultMessage | None:
        result: ResultMessage | None = None
        async for message in query(prompt=user_message, options=options):
            if isinstance(message, ResultMessage):
                result = message
        return result

    try:
        message = await call_with_retry(_call)
    except ClaudeSDKError as exc:
        return ListingResult(succeeded=False, error=str(exc))

    if message is None or message.is_error or message.structured_output is None:
        detail = message.subtype if message else "no result message"
        return ListingResult(succeeded=False, error=str(detail))

    usage = message.usage or {}
    return ListingResult(
        succeeded=True,
        raw_json=json.dumps(message.structured_output),
        cost_usd=message.total_cost_usd or 0.0,
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
    )
