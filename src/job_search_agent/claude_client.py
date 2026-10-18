"""Shared helper for authenticating Agent SDK calls.

Centralised so every agent uses the dedicated Console API key the same way, rather than each
module reloading .env and checking ANTHROPIC_API_KEY itself - see CLAUDE.md "Authentication"
for why every call needs this passed explicitly instead of relying on the ambient environment.

**Two supported auth modes (LLM_AUTH_MODE in .env, "api" by default):**
- "api" - every claude-agent-sdk call gets ANTHROPIC_API_KEY explicitly via `sdk_env()` (below),
  and the raw `anthropic` SDK (fit/batch_client.py) uses `require_api_key()` directly. Metered
  Console billing - needed for unattended/cron runs, since nothing else can run headless.
- "claude_code" - `sdk_env()` returns {} instead, so claude-agent-sdk's subprocess transport
  inherits the ambient environment as-is (it always does this as a base layer regardless - see
  its subprocess_cli.py - `sdk_env()` only controls what gets overlaid on top) and authenticates
  as whatever `claude` CLI session is already logged in on this machine, i.e. a Claude Code/
  claude.ai subscription instead of metered billing. The raw `anthropic` SDK has no equivalent
  (the Batches API - fit/batch_client.py - is Console-billing-only, full stop), so fit/haiku.py,
  fit/sonnet.py, and fit/retry.py each carry a second, per-listing claude-agent-sdk code path for
  this mode instead of submitting a batch.

Every call site must check `auth_mode()`/use `sdk_env()` rather than ever inferring the mode from
"is an API key present" - the whole point of the mode being explicit is that a stray leftover
ANTHROPIC_API_KEY in .env (e.g. after switching modes) must never silently flip real spend back
on. See webapp/onboarding.py step1 and webapp/settings.py for where this gets set.
"""

import os
import sys
from collections.abc import Awaitable, Callable
from typing import Literal, TypeVar

from claude_agent_sdk import ClaudeSDKError
from dotenv import load_dotenv

from job_search_agent.env_utils import ENV_PATH

AuthMode = Literal["api", "claude_code"]


def auth_mode() -> AuthMode:
    load_dotenv(ENV_PATH)
    mode = os.environ.get("LLM_AUTH_MODE", "api").strip().lower()
    return "claude_code" if mode == "claude_code" else "api"


def require_api_key() -> str:
    # Explicit path, not bare load_dotenv() - its cwd/frame-based auto-discovery breaks under
    # mod_wsgi (see docs/apache-vhost.example.conf), where __main__ has no __file__ so
    # python-dotenv silently falls back to os.getcwd() instead of finding the real .env.
    load_dotenv(ENV_PATH)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill in your key.")
    return api_key


def anthropic_env() -> dict[str, str]:
    return {"ANTHROPIC_API_KEY": require_api_key()}


def sdk_env() -> dict[str, str]:
    """What to pass as `ClaudeAgentOptions(env=...)` for any claude-agent-sdk call in this
    project - the Console key in "api" mode, or nothing (ambient `claude` CLI auth) in
    "claude_code" mode. Always use this instead of `anthropic_env()` directly in anything that
    should honour the mode setting (i.e. everything except fit/batch_client.py's raw `anthropic`
    SDK calls, which have no ambient-auth equivalent to fall back to)."""
    return anthropic_env() if auth_mode() == "api" else {}


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
