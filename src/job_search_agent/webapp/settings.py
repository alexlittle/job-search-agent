"""App-level configuration page: edit .env values (API key, contact email, Adzuna credentials),
the fit-agent spend/volume guards (MAX_LISTINGS_PER_RUN, MAX_SPEND_PER_RUN_USD), and which
sources are enabled - all from the dashboard instead of hand-editing config.

.env values write through `env_utils.set_env_var()`, same as onboarding - it updates both the
file and this running process's environment, so a change here takes effect immediately in this
process. `limits.py`'s two guards are read into module-level constants once at import time,
though, so a change here only reaches the *coordinator* (a separate process, started fresh per
run/cron tick) on its next run - not instantly inside an already-running one, which isn't a real
gap since a "run" there is always a fresh process anyway.

Source on/off toggles go in the DB instead (`source_registry.py`, backed by the `settings`
table), not .env - they're a dynamically-discovered, growable list (every RSS feed in
config/sources.yaml plus every bespoke module in sources/), which doesn't fit .env's flat
key=value shape the way a handful of fixed scalars does. Only *disabled* ids are stored, so a
newly-added feed/module shows up here already on, with nothing written for it until someone
turns it off.
"""

import os

from dotenv import load_dotenv
from flask import Blueprint, redirect, render_template, request, url_for

from job_search_agent import db, source_registry
from job_search_agent.env_utils import ENV_PATH, set_env_var

settings_bp = Blueprint("settings", __name__)

# (env var, default shown when unset) - default here is display-only, matching .env.example's
# documented defaults; the real fallback logic lives in limits.py/sources/adzuna.py.
_REQUIRED_KEYS = ["ANTHROPIC_API_KEY", "CONTACT_EMAIL"]
_OPTIONAL_KEYS = [
    ("ADZUNA_APP_ID", ""),
    ("ADZUNA_APP_KEY", ""),
    ("ADZUNA_COUNTRY", "gb"),
    ("MAX_LISTINGS_PER_RUN", "50"),
    ("MAX_SPEND_PER_RUN_USD", "2.00"),
]
ALL_KEYS = _REQUIRED_KEYS + [key for key, _default in _OPTIONAL_KEYS]


def _current_values() -> dict[str, str]:
    # Explicit path - see claude_client.require_api_key for why bare load_dotenv() isn't safe
    # under every deployment (mod_wsgi in particular).
    load_dotenv(ENV_PATH)
    values = {key: os.environ.get(key, "") for key in _REQUIRED_KEYS}
    for key, default in _OPTIONAL_KEYS:
        values[key] = os.environ.get(key) or default
    return values


def _source_rows(disabled: set[str]) -> list[dict]:
    return [
        {
            "id": source_id,
            "label": source_registry.label_for(source_id),
            "kind": "RSS feed" if source_id.startswith("rss:") else "Source",
            "enabled": source_id not in disabled,
        }
        for source_id in source_registry.all_source_ids()
    ]


@settings_bp.route("/settings", methods=["GET", "POST"])
def edit():
    if request.method == "POST":
        for key in ALL_KEYS:
            set_env_var(key, request.form.get(key, "").strip())

        with db.connect() as conn:
            all_ids = source_registry.all_source_ids()
            disabled = {source_id for source_id in all_ids if request.form.get(source_id) != "on"}
            source_registry.set_disabled(conn, disabled)

        return redirect(url_for("settings.edit", saved=1))

    with db.connect() as conn:
        disabled = source_registry.get_disabled(conn)

    return render_template(
        "settings.html",
        values=_current_values(),
        saved=request.args.get("saved"),
        sources=_source_rows(disabled),
    )
