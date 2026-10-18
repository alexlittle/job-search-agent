"""Run-level cost/volume guards for the fit-agent batches (Phase 12) - a second line of defense
underneath the Anthropic Console spend cap docs/brief.md already recommends setting directly on
the account. Configurable via .env, matching how the rest of this project's personal config
works, rather than hardcoded, so a change doesn't need a code edit.
"""

import os

from dotenv import load_dotenv

from job_search_agent.claude_client import auth_mode
from job_search_agent.env_utils import ENV_PATH
from job_search_agent.pricing import estimate_cost_usd, estimate_tokens


def _int_env(name: str, default: int) -> int:
    # Explicit path - see claude_client.require_api_key for why bare load_dotenv() isn't safe
    # under every deployment (mod_wsgi in particular).
    load_dotenv(ENV_PATH)
    value = os.environ.get(name)
    return int(value) if value else default


def _float_env(name: str, default: float) -> float:
    load_dotenv(ENV_PATH)
    value = os.environ.get(name)
    return float(value) if value else default


MAX_LISTINGS_PER_RUN = _int_env("MAX_LISTINGS_PER_RUN", 50)
MAX_SPEND_PER_RUN_USD = _float_env("MAX_SPEND_PER_RUN_USD", 2.00)


class SpendGuardExceeded(Exception):
    pass


def cap_listings(rows: list, stage: str) -> list:
    """Caps how many listings a single Haiku/Sonnet batch will process - protects against, e.g., a
    pre-filter bug suddenly letting hundreds of listings through in one run. Anything past the cap
    is simply left for the next run (nothing is lost, just deferred)."""
    if len(rows) <= MAX_LISTINGS_PER_RUN:
        return rows
    print(
        f"[{stage}] {len(rows)} listing(s) queued, capped at MAX_LISTINGS_PER_RUN="
        f"{MAX_LISTINGS_PER_RUN} - the other {len(rows) - MAX_LISTINGS_PER_RUN} will be picked up "
        "next run."
    )
    return rows[:MAX_LISTINGS_PER_RUN]


def check_spend_cap(
    model: str, system_text: str, user_texts: list[str], max_tokens: int, batch: bool = True
) -> None:
    """Pre-flight estimate of a run's worst-case cost (every request generating the full
    `max_tokens`, ignoring the discount prompt caching would give the actual bill) before it's
    submitted. `batch` should match how these requests will actually run - the Batches API
    (True, the "api" auth mode's fit/haiku.py etc.) is priced 50% off vs. a synchronous
    claude-agent-sdk call per listing (False, the "claude_code" auth mode's fallback path).

    In "api" mode this raises SpendGuardExceeded rather than silently submitting something far
    bigger than expected - a real guard against real billing. In "claude_code" mode there's no
    real bill this is protecting against (auth_mode.__doc__), so it only prints a warning and
    lets the run continue - MAX_LISTINGS_PER_RUN is still the volume guard that applies either
    way."""
    system_tokens = estimate_tokens(system_text)
    total_input = sum(system_tokens + estimate_tokens(text) for text in user_texts)
    total_output = max_tokens * len(user_texts)
    estimated = estimate_cost_usd(model, total_input, total_output, batch=batch)
    if estimated <= MAX_SPEND_PER_RUN_USD:
        return

    if auth_mode() == "claude_code":
        print(
            f"[warn] Estimated cost-equivalent for this run (${estimated:.2f}, "
            f"{len(user_texts)} request(s)) is above MAX_SPEND_PER_RUN_USD "
            f"(${MAX_SPEND_PER_RUN_USD:.2f}) - not a real bill under Claude Code auth, "
            "continuing anyway."
        )
        return

    raise SpendGuardExceeded(
        f"Estimated worst-case cost for this batch (${estimated:.2f}, {len(user_texts)} "
        f"request(s)) exceeds MAX_SPEND_PER_RUN_USD (${MAX_SPEND_PER_RUN_USD:.2f}). Raise the "
        "limit in .env if a run this large is expected, or lower MAX_LISTINGS_PER_RUN."
    )
