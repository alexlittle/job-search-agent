"""Cheap, non-LLM pre-filtering of listings, using profile/criteria.yaml.

Runs before anything reaches the fit agents (Phase 6/7) - only catches "obviously wrong"
listings: a dealbreaker/avoid keyword, or a location or role type with zero word overlap with
your criteria. Anything even slightly ambiguous is left for the LLM to judge properly rather
than guessed at here - a wrongly-*kept* listing just costs a bit of LLM budget later, but a
wrongly-*filtered* one is lost for good, so these checks are deliberately permissive (they only
filter on a clear absence of any matching signal, never on a partial/fuzzy mismatch).

Run with: uv run python -m job_search_agent.filters
"""

import re

from job_search_agent import db
from job_search_agent.profile import Criteria, load_profile

# Filler words that show up in almost every free-text location/role phrase and carry no
# meaning on their own - dropped before comparing, so they can't cause a spurious match
# (e.g. "on-site" contributing "on", which would otherwise match inside unrelated words).
_STOPWORDS = {
    "on", "site", "or", "hybrid", "open", "to", "in", "based", "including", "options",
    "wide", "and", "the", "of", "a",
}

# A few manual phrase synonyms for common wording gaps - added after finding real listings
# that spell out "United Kingdom" instead of "UK" (e.g. "Liverpool, United Kingdom"). These are
# checked as whole phrases against the raw text, not as individual words - a loose word-level
# synonym for "uk" like "united" would also match "United Arab Emirates", which is exactly the
# kind of false match this pre-filter needs to avoid.
_LOCATION_PHRASE_SYNONYMS = {
    "uk": ("united kingdom", "great britain"),
}

# Same idea for role words that are commonly spelled out in full rather than abbreviated.
_ROLE_PHRASE_SYNONYMS = {
    "ai": ("artificial intelligence",),
    "ml": ("machine learning",),
}

# Generic job-title words that appear across virtually every professional role regardless of
# domain (a "Mechanical Engineer" and an "AI/ML Engineer" share "engineer"). Left in, these
# made the role-type check match almost anything; dropped, only the words that actually signal
# a *domain* ("ai", "python", "healthcare", ...) count towards a match.
_ROLE_CONNECTOR_WORDS = {
    "engineer", "developer", "manager", "scientist", "researcher", "analyst", "specialist",
    "lead", "senior", "junior", "associate", "assistant", "director", "professor", "fellow",
    "coordinator", "consultant", "advisor", "architect", "administrator", "officer",
    "executive", "head", "chief",
}


def extract_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 1 and w not in _STOPWORDS}


def extract_domain_words(text: str) -> set[str]:
    return extract_words(text) - _ROLE_CONNECTOR_WORDS


def _phrase_synonym_match(
    criteria_words: set[str], raw_text: str, synonyms: dict[str, tuple[str, ...]]
) -> bool:
    lowered = raw_text.lower()
    return any(phrase in lowered for word in criteria_words for phrase in synonyms.get(word, ()))


def words_match(a: str, b: str) -> bool:
    """Exact match for short words (stops e.g. "uk" matching inside "ukraine"); substring
    match either way for longer ones (so "world" matches "worldwide")."""
    if len(a) <= 3 or len(b) <= 3:
        return a == b
    return a in b or b in a


def _any_word_matches(words_a: set[str], words_b: set[str]) -> bool:
    return any(words_match(a, b) for a in words_a for b in words_b)


def _contains_any(text: str, terms: list[str]) -> str | None:
    lowered = text.lower()
    for term in terms:
        if term and term.lower() in lowered:
            return term
    return None


def filter_reason(title: str, description: str, location: str, criteria: Criteria) -> str | None:
    """Return a human-readable reason to filter this listing out, or None to keep it."""
    text = f"{title} {description}"

    dealbreaker = _contains_any(text, criteria.dealbreakers)
    if dealbreaker:
        return f"Dealbreaker keyword matched: {dealbreaker!r}"

    avoid = _contains_any(text, criteria.keywords_avoid)
    if avoid:
        return f"Avoid keyword matched: {avoid!r}"

    criteria_location_words = set()
    for loc in criteria.locations:
        criteria_location_words |= extract_words(loc)
    listing_location_words = extract_words(location)
    if criteria_location_words and listing_location_words:
        matches = _any_word_matches(
            criteria_location_words, listing_location_words
        ) or _phrase_synonym_match(criteria_location_words, location, _LOCATION_PHRASE_SYNONYMS)
        if not matches:
            return f"Location {location!r} doesn't overlap with any target location"

    role_words = set()
    for role in criteria.roles:
        role_words |= extract_domain_words(role)
    for keyword in criteria.keywords_boost:
        role_words |= extract_domain_words(keyword)
    # Title only, not the full description - job board descriptions are often long,
    # marketing-heavy pages that incidentally mention buzzwords ("AI", "data", "product")
    # regardless of the actual role (a Mechanical Engineer posting at an AI company still
    # says "AI" somewhere), which made this check pass almost everything when run against the
    # full text. Titles are short and specific enough that this false-positive rate drops a lot.
    title_words = extract_words(title)
    if role_words and title_words:
        matches = bool(role_words & title_words) or _phrase_synonym_match(
            role_words, title, _ROLE_PHRASE_SYNONYMS
        )
        if not matches:
            return "No overlap with any target role or boost keyword - likely the wrong role type"

    return None


def run_filters() -> None:
    profile = load_profile()
    filtered = 0
    kept = 0
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM listings WHERE status = 'new'").fetchall()
        for row in rows:
            reason = filter_reason(
                row["title"], row["description"], row["location"], profile.criteria
            )
            if reason:
                conn.execute(
                    "UPDATE listings SET status = 'filtered', status_reason = ? WHERE id = ?",
                    (reason, row["id"]),
                )
                db.log_event(conn, stage="filter", message=reason, listing_id=row["id"])
                filtered += 1
            else:
                conn.execute("UPDATE listings SET status = 'pending_fit' WHERE id = ?", (row["id"],))
                kept += 1
        db.log_event(
            conn,
            stage="filter",
            message=f"Pre-filter run: {filtered} filtered out, {kept} kept for scoring",
        )
    print(f"Filtered {filtered} listing(s), kept {kept} for scoring.")


if __name__ == "__main__":
    run_filters()
