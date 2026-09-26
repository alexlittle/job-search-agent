"""Per-token USD pricing for the models this project calls via the raw `anthropic` SDK (the
Message Batches API, Phase 12). Unlike `claude-agent-sdk`'s synchronous `query()`, which reports
`total_cost_usd` on every `ResultMessage` for free, the Batches API only returns raw token counts
- this project has to price them itself.

Figures are Anthropic's per-million-token list prices as of 2026-09 (see
https://www.anthropic.com/pricing) - treat `estimate_cost_usd` as a dashboard estimate for
tracking relative spend, not a source of truth for billing; check the real invoice if it matters.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrices:
    input_per_mtok: float
    output_per_mtok: float
    cache_write_per_mtok: float
    cache_read_per_mtok: float


PRICES: dict[str, ModelPrices] = {
    "claude-haiku-4-5-20251001": ModelPrices(
        input_per_mtok=1.00, output_per_mtok=5.00, cache_write_per_mtok=1.25, cache_read_per_mtok=0.10
    ),
    "claude-sonnet-5": ModelPrices(
        input_per_mtok=3.00, output_per_mtok=15.00, cache_write_per_mtok=3.75, cache_read_per_mtok=0.30
    ),
}

# Anthropic bills Message Batches API usage at half the synchronous per-token price.
BATCH_DISCOUNT = 0.5


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
    batch: bool = True,
) -> float:
    prices = PRICES[model]
    cost = (
        input_tokens * prices.input_per_mtok
        + output_tokens * prices.output_per_mtok
        + cache_creation_input_tokens * prices.cache_write_per_mtok
        + cache_read_input_tokens * prices.cache_read_per_mtok
    ) / 1_000_000
    return cost * BATCH_DISCOUNT if batch else cost


def estimate_tokens(text: str) -> int:
    """Rough chars-to-tokens heuristic (~4 chars/token for English) for a pre-flight cost
    estimate before a batch is submitted - see `limits.py`. Not meant to be precise, just a
    conservative-enough ballpark to catch a batch that's unexpectedly huge before spending on it."""
    return max(1, len(text) // 4)
