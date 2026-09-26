"""Fetches job listings from the Adzuna API (https://developer.adzuna.com/).

The first bespoke (non-RSS) structured source (Phase 13) - proves the plugin interface described
in sources/__init__.py actually holds up for something that isn't plain RSS: real auth
(app_id/app_key query params, not just a User-Agent), and a JSON response shape to map onto
Listing ourselves rather than feedparser doing it generically.

Credentials (ADZUNA_APP_ID, ADZUNA_APP_KEY) are optional at the pipeline level, unlike
ANTHROPIC_API_KEY/CONTACT_EMAIL - a fresh clone with nothing but the free sources configured
should still run. ingest.ingest_adzuna checks have_credentials() and skips (logged, not a crash)
rather than calling anything here if they're unset; require_credentials() below is only for
running this module directly, where a clear exit message is more useful than a bare KeyError.

No cost_log entries here - Adzuna's free tier isn't billed per Claude-style token cost, so unlike
the web_search source there's nothing to price.

Run with: uv run python -m job_search_agent.sources.adzuna [role]
(omit role to search once per role in profile/criteria.yaml, same pattern as web_search.py)
"""

import os
import sys

import requests
from dotenv import load_dotenv

from job_search_agent.listing import Listing
from job_search_agent.profile import load_criteria
from job_search_agent.user_agent import build_user_agent

BASE_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
DEFAULT_COUNTRY = "gb"
RESULTS_PER_PAGE = 20
SOURCE_NAME = "adzuna"


def have_credentials() -> bool:
    load_dotenv()
    return bool(os.environ.get("ADZUNA_APP_ID")) and bool(os.environ.get("ADZUNA_APP_KEY"))


def require_credentials() -> tuple[str, str]:
    load_dotenv()
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        sys.exit(
            "ADZUNA_APP_ID/ADZUNA_APP_KEY are not set. Register an app at "
            "https://developer.adzuna.com/ (separate from a regular Adzuna job-seeker account) "
            "and add both to .env."
        )
    return app_id, app_key


def _location_text(location: dict) -> str:
    # Adzuna's display_name is often just the city/county ("Belfast, Northern Ireland") and
    # doesn't repeat the country - but filters.py's location pre-filter is plain word-overlap
    # matching, so a criteria entry like "UK-wide" can only ever match listings whose location
    # text literally contains "UK" somewhere. `area` is Adzuna's own broad-to-narrow hierarchy
    # (e.g. ["UK", "Northern Ireland", "Belfast"]) - area[0] is the country, so append it when
    # display_name doesn't already mention it.
    display_name = location.get("display_name", "")
    area = location.get("area") or []
    if not area:
        return display_name
    country = area[0]
    if not display_name or country.lower() in display_name.lower():
        return display_name
    return f"{display_name}, {country}"


def _to_listing(item: dict) -> Listing:
    return Listing(
        source=SOURCE_NAME,
        title=item.get("title", ""),
        company=(item.get("company") or {}).get("display_name", ""),
        url=item.get("redirect_url", ""),
        location=_location_text(item.get("location") or {}),
        posted_date=item.get("created"),
        description=item.get("description", ""),
    )


def fetch_listings(
    what: str, country: str = DEFAULT_COUNTRY, results_per_page: int = RESULTS_PER_PAGE
) -> list[Listing]:
    """The plugin interface entry point (see sources/__init__.py) - one page of results for a
    single search term."""
    app_id, app_key = require_credentials()
    response = requests.get(
        BASE_URL.format(country=country, page=1),
        params={
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": results_per_page,
            "what": what,
            "content-type": "application/json",
        },
        headers={"User-Agent": build_user_agent()},
        timeout=15,
    )
    response.raise_for_status()
    return [_to_listing(item) for item in response.json().get("results", [])]


def fetch_all(role: str | None = None, country: str = DEFAULT_COUNTRY) -> list[Listing]:
    roles = [role] if role else load_criteria().roles
    listings: list[Listing] = []
    for one_role in roles:
        listings.extend(fetch_listings(one_role, country=country))
    return listings


def main() -> None:
    role = sys.argv[1] if len(sys.argv) > 1 else None
    listings = fetch_all(role=role)
    for listing in listings:
        print(f"- [{listing.company}] {listing.title} ({listing.location})")
        print(f"  {listing.url}")
    print(f"\n{len(listings)} listing(s) fetched from Adzuna (role={role or 'all configured roles'}).")


if __name__ == "__main__":
    main()
