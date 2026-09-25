"""Fetches job listings from THE (Times Higher Education) unijobs' RSS feed.

Plain Python, no LLM involved - this is Phase 2's first source agent. jobs.ac.uk was the
original target here but no longer publishes a public RSS feed (checked 2026-09-25); THE
unijobs is a comparable UK/international academic & research jobs board that still does.
See tasks.md Phase 2.

Feed entries look like:
    title:   "COMPANY NAME: Role title"
    summary: "[optional salary line:]\\nCOMPANY NAME:\\ndescription text\\nLocation, Country"

Run with: uv run python -m job_search_agent.sources.the_unijobs [keywords]
"""

import sys

import feedparser
import requests

from job_search_agent.listing import Listing

FEED_URL = "https://www.timeshighereducation.com/unijobs/jobsrss/"
SOURCE_NAME = "the_unijobs"
USER_AGENT = "job-search-agent/0.1 (personal project; contact alex@alexlittle.net)"


def fetch_listings(keywords: str, country_code: str = "GB") -> list[Listing]:
    response = requests.get(
        FEED_URL,
        params={"keywords": keywords, "countrycode": country_code},
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    response.raise_for_status()
    feed = feedparser.parse(response.content)

    listings = []
    for entry in feed.entries:
        company, _, title = entry.title.partition(": ")
        if not title:
            company, title = "", company

        lines = [line.strip() for line in entry.summary.split("\n") if line.strip()]
        location = lines[-1] if lines else ""

        listings.append(
            Listing(
                source=SOURCE_NAME,
                title=title,
                company=company,
                url=entry.link,
                location=location,
                posted_date=entry.get("published"),
                description=entry.summary,
            )
        )
    return listings


def main() -> None:
    keywords = sys.argv[1] if len(sys.argv) > 1 else "python"
    listings = fetch_listings(keywords=keywords)
    for listing in listings:
        print(f"- [{listing.company}] {listing.title} ({listing.location})")
        print(f"  {listing.url}")
    print(f"\n{len(listings)} listing(s) fetched for keywords={keywords!r}.")


if __name__ == "__main__":
    main()
