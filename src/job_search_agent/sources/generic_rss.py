"""Fetches job listings from any plain RSS feed described in config/sources.yaml.

This is what lets a non-programmer add a new RSS-based source: add an entry to the config file
(name, URL, query params, and a couple of parsing hints), no Python required. Feeds whose
structure doesn't fit the supported hints need a bespoke module instead - see
src/job_search_agent/sources/__init__.py for that interface.

Run with: uv run python -m job_search_agent.sources.generic_rss [feed_name] [keywords]
(omit feed_name to run every configured feed; omit keywords for feeds that don't need one)
"""

import sys
from pathlib import Path

import feedparser
import requests
import yaml

from job_search_agent.listing import Listing

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "sources.yaml"
USER_AGENT = "job-search-agent/0.1 (personal project; contact alex@alexlittle.net)"


def load_feed_configs() -> list[dict]:
    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    return data.get("feeds", [])


def _resolve_query(query: dict, keywords: str) -> dict:
    return {key: value.format(keywords=keywords) for key, value in query.items()}


def _split_title(raw_title: str, title_format: str) -> tuple[str, str]:
    if title_format == "company_colon_title":
        company, sep, title = raw_title.partition(": ")
        if sep:
            return company, title
    return "", raw_title


def _extract_location(entry: dict, location: str) -> str:
    if location == "summary_last_line":
        lines = [line.strip() for line in entry.get("summary", "").split("\n") if line.strip()]
        return lines[-1] if lines else ""
    if location.startswith("field:"):
        return entry.get(location.removeprefix("field:"), "")
    return ""


def fetch_feed(feed_config: dict, keywords: str = "") -> list[Listing]:
    params = _resolve_query(feed_config.get("query", {}), keywords)
    response = requests.get(
        feed_config["url"],
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    response.raise_for_status()
    feed = feedparser.parse(response.content)

    listings = []
    for entry in feed.entries:
        company, title = _split_title(entry.title, feed_config.get("title_format", "plain"))
        listings.append(
            Listing(
                source=feed_config["name"],
                title=title,
                company=company,
                url=entry.link,
                location=_extract_location(entry, feed_config.get("location", "none")),
                posted_date=entry.get("published"),
                description=entry.get("summary", ""),
            )
        )
    return listings


def fetch_all(keywords: str = "", feed_name: str | None = None) -> list[Listing]:
    listings = []
    for feed_config in load_feed_configs():
        if feed_name and feed_config["name"] != feed_name:
            continue
        listings.extend(fetch_feed(feed_config, keywords=keywords))
    return listings


def main() -> None:
    feed_name = sys.argv[1] if len(sys.argv) > 1 else None
    keywords = sys.argv[2] if len(sys.argv) > 2 else "python"

    listings = fetch_all(keywords=keywords, feed_name=feed_name)
    for listing in listings:
        print(f"- [{listing.source}] [{listing.company}] {listing.title} ({listing.location})")
        print(f"  {listing.url}")
    print(f"\n{len(listings)} listing(s) fetched (feed={feed_name or 'all'}, keywords={keywords!r}).")


if __name__ == "__main__":
    main()
