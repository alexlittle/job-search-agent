"""Shared helper for authenticating Agent SDK calls.

Centralised so every agent uses the dedicated Console API key the same way, rather than each
module reloading .env and checking ANTHROPIC_API_KEY itself - see CLAUDE.md "Authentication"
for why every call needs this passed explicitly instead of relying on the ambient environment.
"""

import os
import sys

from dotenv import load_dotenv


def require_api_key() -> str:
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill in your key.")
    return api_key


def anthropic_env() -> dict[str, str]:
    return {"ANTHROPIC_API_KEY": require_api_key()}
