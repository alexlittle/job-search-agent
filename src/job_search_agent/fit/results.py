"""Transport-agnostic result of one fit-agent call for one listing.

Whichever of the two ways this project can reach Claude for a listing produced it - the Batches
API (fit/batch_client.py, "api" auth mode) or a single claude-agent-sdk query() (fit/sdk_calls.py,
"claude_code" auth mode, see claude_client.py's module docstring) - fit/haiku.py's and
fit/sonnet.py's own schema-specific parsing and DB-writing loop only ever see this shape. Each
stage converts whichever transport it used into this right before its per-row loop - see each
stage's run_*_pass().
"""

from dataclasses import dataclass


@dataclass
class ListingResult:
    succeeded: bool
    raw_json: str | None = None  # the model's structured-output JSON, as text - not yet parsed
    cost_usd: float = 0.0
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None
