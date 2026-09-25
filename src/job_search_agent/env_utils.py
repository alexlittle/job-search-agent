"""Writes a value into .env and into the current process's environment at the same time.

Used by onboarding (Phase 8) - a plain `dotenv.set_key()` call updates the file but not the
already-running process's `os.environ`, which would mean a value set via the dashboard wouldn't
take effect until a restart. This does both.
"""

import os
from pathlib import Path

from dotenv import set_key

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def set_env_var(key: str, value: str) -> None:
    ENV_PATH.touch()
    set_key(str(ENV_PATH), key, value)
    os.environ[key] = value
