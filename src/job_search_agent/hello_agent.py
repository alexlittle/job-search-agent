"""Phase 0 sanity check: one Claude call via the Agent SDK, using our own API key.

Run with: uv run python -m job_search_agent.hello_agent
"""

import asyncio

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query

from job_search_agent.claude_client import anthropic_env

MODEL = "claude-haiku-4-5-20251001"


async def main() -> None:
    options = ClaudeAgentOptions(
        model=MODEL,
        max_turns=1,
        tools=[],
        env=anthropic_env(),
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
