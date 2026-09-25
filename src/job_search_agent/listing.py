"""The common shape every job source agent (RSS, API, or search-based) produces.

Keeping this shape source-agnostic is what lets Phase 4's dedupe/storage and the fit agents
work the same way regardless of where a listing came from.
"""

from dataclasses import dataclass


@dataclass
class Listing:
    source: str
    title: str
    company: str
    url: str
    location: str
    posted_date: str | None
    description: str
