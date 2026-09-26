"""Run-level cost/volume guards for the fit-agent batches (Phase 12) - a second line of defense
underneath the Anthropic Console spend cap docs/brief.md already recommends setting directly on
the account. Configurable via .env, matching how the rest of this project's personal config
works, rather than hardcoded, so a change doesn't need a code edit.
"""

import os

from dotenv import load_dotenv

from job_search_agent.pricing import estimate_cost_usd, estimate_tokens


def _int_env(name: str, default: int) -> int:
    load_dotenv()
    value = os.environ.get(name)
    return int(value) if value else default


def _float_env(name: str, default: float) -> float:
    load_dotenv()
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


def check_spend_cap(model: str, system_text: str, user_texts: list[str], max_tokens: int) -> None:
    """Pre-flight estimate of a batch's worst-case cost (every request generating the full
    `max_tokens`, ignoring the discount prompt caching would give the actual bill) before it's
    submitted. Raises SpendGuardExceeded rather than silently submitting a batch far bigger than
    expected - deliberately erring conservative, since this is a safety net, not a cost forecast."""
    system_tokens = estimate_tokens(system_text)
    total_input = sum(system_tokens + estimate_tokens(text) for text in user_texts)
    total_output = max_tokens * len(user_texts)
    estimated = estimate_cost_usd(model, total_input, total_output, batch=True)
    if estimated > MAX_SPEND_PER_RUN_USD:
        raise SpendGuardExceeded(
            f"Estimated worst-case cost for this batch (${estimated:.2f}, {len(user_texts)} "
            f"request(s)) exceeds MAX_SPEND_PER_RUN_USD (${MAX_SPEND_PER_RUN_USD:.2f}). Raise the "
            "limit in .env if a run this large is expected, or lower MAX_LISTINGS_PER_RUN."
        )
