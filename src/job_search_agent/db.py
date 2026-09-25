"""Local SQLite storage: listings, an activity log, and a cost log.

One file (data/job_search.db, gitignored - personal data), shared by every stage of the
pipeline. See tasks.md Phase 4.

Dedupe is by normalized (title, company), not URL - the same posting on two different boards
will have two different URLs, so matching on URL would miss exactly the cross-source duplicates
this is meant to catch. The tradeoff is that two genuinely different postings with an identical
title at the same company would incorrectly merge; acceptable for a personal tool, and easy to
revisit later if it causes real problems.
"""

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from job_search_agent.listing import Listing

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "job_search.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    url TEXT NOT NULL,
    location TEXT NOT NULL,
    posted_date TEXT,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    status_reason TEXT NOT NULL DEFAULT '',
    first_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    stage TEXT NOT NULL,
    message TEXT NOT NULL,
    listing_id INTEGER REFERENCES listings(id)
);

CREATE TABLE IF NOT EXISTS cost_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    stage TEXT NOT NULL,
    model TEXT NOT NULL,
    num_turns INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
"""


def dedupe_key(title: str, company: str) -> str:
    normalized = f"{title.strip().lower()}|{company.strip().lower()}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def save_listings(conn: sqlite3.Connection, listings: list[Listing]) -> int:
    """Insert listings not already seen. Returns how many were actually new."""
    inserted = 0
    now = datetime.now(UTC).isoformat()
    for listing in listings:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO listings
                (dedupe_key, source, title, company, url, location, posted_date, description,
                 status, first_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)
            """,
            (
                dedupe_key(listing.title, listing.company),
                listing.source,
                listing.title,
                listing.company,
                listing.url,
                listing.location,
                listing.posted_date,
                listing.description,
                now,
            ),
        )
        if cursor.rowcount:
            inserted += 1
    return inserted


def log_event(
    conn: sqlite3.Connection, stage: str, message: str, listing_id: int | None = None
) -> None:
    conn.execute(
        "INSERT INTO events (timestamp, stage, message, listing_id) VALUES (?, ?, ?, ?)",
        (datetime.now(UTC).isoformat(), stage, message, listing_id),
    )


def log_cost(
    conn: sqlite3.Connection,
    stage: str,
    model: str,
    num_turns: int,
    cost_usd: float,
    detail: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO cost_log (timestamp, stage, model, num_turns, cost_usd, detail)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (datetime.now(UTC).isoformat(), stage, model, num_turns, cost_usd, detail),
    )
