"""Shared helper for authenticating Agent SDK calls.

Centralised so every agent uses the dedicated Console API key the same way, rather than each
module reloading .env and checking ANTHROPIC_API_KEY itself - see CLAUDE.md "Authentication"
for why every call needs this passed explicitly instead of relying on the ambient environment.
"""

import os
import sys
from collections.abc import Awaitable, Callable
from typing import TypeVar

from claude_agent_sdk import ClaudeSDKError
from dotenv import load_dotenv


def require_api_key() -> str:
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill in your key.")
    return api_key


def anthropic_env() -> dict[str, str]:
    return {"ANTHROPIC_API_KEY": require_api_key()}


T = TypeVar("T")

# The course this project follows builds toward exactly this by its final day: a retry cap per
# agent call, so a single flaky response can't crash an entire batch (nor retry forever). Two
# attempts, not open-ended - if the SDK/API is genuinely having a bad moment, one retry either
# recovers it or it won't, and the caller should give up on that one item and move on rather than
# hold up everything else in the run.
MAX_AGENT_ATTEMPTS = 2


async def call_with_retry(call: Callable[[], Awaitable[T]], attempts: int = MAX_AGENT_ATTEMPTS) -> T:
    """Runs an async zero-arg callable, retrying on ClaudeSDKError (e.g. the transient "reached
    maximum number of turns" error seen in real use) up to `attempts` times. Raises the last error
    if every attempt fails - it's the caller's job to decide what "giving up" means for that item
    (skip it and continue, typically), not this helper's."""
    last_error: ClaudeSDKError | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await call()
        except ClaudeSDKError as exc:
            last_error = exc
            if attempt < attempts:
                continue
    assert last_error is not None
    raise last_error
