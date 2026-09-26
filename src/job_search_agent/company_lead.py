"""The shape a company/startup discovery agent produces - deliberately distinct from Listing
(see listing.py). A company lead is "worth following, might be worth a speculative application",
not "here's a role to apply for" - different judgement, different fields (no title/posted_date; a
sector/stage instead, and why_relevant explains fit against the candidate generally rather than
against one specific posting). See tasks.md Phase 15.
"""

from dataclasses import dataclass


@dataclass
class CompanyLead:
    name: str
    sector: str
    stage: str
    why_relevant: str
    careers_url: str
    notes: str
    source: str
