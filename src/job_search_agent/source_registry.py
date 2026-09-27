"""Discovers which job/company sources exist right now, so the dashboard's Settings page (and
the pipeline itself) can list and gate them without a hardcoded list that would drift as sources
are added - see `sources/__init__.py` for the two ways a source gets added in the first place.

Every source defaults to *enabled*: only explicitly-disabled identifiers are stored (in the DB's
`settings` table, under `DISABLED_SOURCES_KEY`, as a JSON list - see `db.get_setting`/
`set_setting`), so a newly-added RSS feed or a newly-added bespoke module is on by default with
nothing to write for it - the opposite of an enabled-list, which would silently leave a new
source off until someone remembered to add it here.

Two kinds of source, both auto-discovered:
- RSS feeds (`rss:<name>`) - one per entry in config/sources.yaml, read via `generic_rss`.
- Bespoke modules (`source:<module>`) - any .py file directly inside `sources/` other than
  `generic_rss` (config-driven, enumerated per-feed instead above) or `__init__`. Adding a new
  bespoke source module (per the plugin interface) makes it show up here automatically, no edit
  needed in this file.
"""

import json
import pkgutil
import sqlite3

from job_search_agent import db, sources
from job_search_agent.sources import generic_rss

DISABLED_SOURCES_KEY = "disabled_sources"

_SKIP_MODULES = {"generic_rss"}


def _bespoke_module_names() -> list[str]:
    return sorted(
        name
        for _finder, name, is_pkg in pkgutil.iter_modules(sources.__path__)
        if not is_pkg and name not in _SKIP_MODULES and not name.startswith("_")
    )


def rss_feed_ids() -> list[str]:
    return [f"rss:{feed['name']}" for feed in generic_rss.load_feed_configs()]


def module_source_ids() -> list[str]:
    return [f"source:{name}" for name in _bespoke_module_names()]


def all_source_ids() -> list[str]:
    return rss_feed_ids() + module_source_ids()


def label_for(source_id: str) -> str:
    _prefix, _sep, name = source_id.partition(":")
    return name.replace("_", " ").title()


def get_disabled(conn: sqlite3.Connection) -> set[str]:
    raw = db.get_setting(conn, DISABLED_SOURCES_KEY)
    return set(json.loads(raw)) if raw else set()


def set_disabled(conn: sqlite3.Connection, disabled: set[str]) -> None:
    db.set_setting(conn, DISABLED_SOURCES_KEY, json.dumps(sorted(disabled)))


def is_enabled(conn: sqlite3.Connection, source_id: str) -> bool:
    return source_id not in get_disabled(conn)
