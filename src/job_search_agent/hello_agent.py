"""Phase 0 sanity check: one Claude call via the Agent SDK, using our own API key.

Run with: uv run python -m job_search_agent.hello_agent
"""

import asyncio
import os
import sys

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query
from dotenv import load_dotenv

MODEL = "claude-haiku-4-5-20251001"


async def main() -> None:
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill in your key."
        )

    options = ClaudeAgentOptions(
        model=MODEL,
        max_turns=1,
        tools=[],
        env={"ANTHROPIC_API_KEY": api_key},
    )

    async for message in query(
        prompt="In one short sentence, confirm you're online and name your model.",
        options=options,
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(block.text)
        elif isinstance(message, ResultMessage):
            print(
                f"\n[{message.num_turns} turn(s), "
                f"${message.total_cost_usd:.6f} estimated cost]"
            )


if __name__ == "__main__":
    asyncio.run(main())
