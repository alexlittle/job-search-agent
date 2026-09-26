"""Loads the user's CV + job-search criteria into a single context block for the agents.

The CV lives in profile/cv.md (gitignored) - see profile/cv.example.md for the format.
Criteria live in the database - the dashboard's onboarding wizard (Phase 8) collects them via a
form on first run and the criteria page is how you change them after that. `load_criteria()` can
also seed the DB from a hand-written profile/criteria.yaml if one exists, for anyone who prefers
running the pipeline scripts directly over using the dashboard, but that file isn't required.

Run with: uv run python -m job_search_agent.profile
"""

import os
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from job_search_agent import db

DEFAULT_PROFILE_DIR = Path(__file__).resolve().parents[2] / "profile"

# Phase 10: how many past feedback examples to feed into the fit-agent prompts. Capped rather
# than "all of it" so the prompt doesn't grow unbounded as feedback accumulates over months of
# use - 20 recent examples is enough to show a pattern without dominating the prompt next to the
# CV and criteria.
FEEDBACK_EXAMPLES_LIMIT = 20


@dataclass
class Criteria:
    roles: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    salary_currency: str | None = None
    salary_minimum: float | None = None
    must_haves: list[str] = field(default_factory=list)
    dealbreakers: list[str] = field(default_factory=list)
    keywords_boost: list[str] = field(default_factory=list)
    keywords_avoid: list[str] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "Criteria":
        salary = data.get("salary") or {}
        keywords = data.get("keywords") or {}
        return cls(
            roles=data.get("roles") or [],
            locations=data.get("locations") or [],
            salary_currency=salary.get("currency"),
            salary_minimum=salary.get("minimum"),
            must_haves=data.get("must_haves") or [],
            dealbreakers=data.get("dealbreakers") or [],
            keywords_boost=keywords.get("boost") or [],
            keywords_avoid=keywords.get("avoid") or [],
            notes=(data.get("notes") or "").strip(),
        )

    def to_dict(self) -> dict:
        return {
            "roles": self.roles,
            "locations": self.locations,
            "salary": {"currency": self.salary_currency, "minimum": self.salary_minimum},
            "must_haves": self.must_haves,
            "dealbreakers": self.dealbreakers,
            "keywords": {"boost": self.keywords_boost, "avoid": self.keywords_avoid},
            "notes": self.notes,
        }


@dataclass
class Profile:
    cv_text: str
    criteria: Criteria

    def as_prompt_context(self) -> str:
        c = self.criteria
        salary = (
            f"{c.salary_minimum} {c.salary_currency or ''}".strip()
            if c.salary_minimum
            else "(not specified)"
        )
        lines = [
            "## Candidate CV",
            "",
            self.cv_text.strip(),
            "",
            "## Job search criteria",
            f"- Target roles: {', '.join(c.roles) or '(not specified)'}",
            f"- Locations: {', '.join(c.locations) or '(not specified)'}",
            f"- Minimum salary: {salary}",
            f"- Must-haves: {', '.join(c.must_haves) or '(none specified)'}",
            f"- Dealbreakers: {', '.join(c.dealbreakers) or '(none specified)'}",
            f"- Boost keywords: {', '.join(c.keywords_boost) or '(none)'}",
            f"- Avoid keywords: {', '.join(c.keywords_avoid) or '(none)'}",
        ]
        if c.notes:
            lines.append(f"- Notes: {c.notes}")
        return "\n".join(lines)


def feedback_examples_context(conn: sqlite3.Connection, limit: int = FEEDBACK_EXAMPLES_LIMIT) -> str:
    """Renders past relevant/not_relevant feedback as a prompt block, so the fit agents can learn
    from what the candidate has already told them - "here are jobs I said yes/no to before, and
    why, if known" (Phase 10). Returns "" once there's no feedback yet, so early runs (before any
    feedback exists) get an unchanged prompt rather than an empty section header."""
    rows = db.get_feedback_examples(conn, limit=limit)
    if not rows:
        return ""

    lines = [
        "## Feedback from past listings",
        "The candidate has already given feedback on these listings from earlier runs. Use it to "
        "calibrate judgement on similar listings - if a reason is given, it's the candidate's own "
        "explanation, more informative than the listing alone.",
    ]
    for row in rows:
        verdict = "RELEVANT" if row["feedback"] == "relevant" else "NOT RELEVANT"
        line = f"- [{verdict}] {row['title']} at {row['company']}"
        if row["feedback_note"]:
            line += f' - candidate said: "{row["feedback_note"]}"'
        lines.append(line)
    return "\n".join(lines)


def company_feedback_examples_context(
    conn: sqlite3.Connection, limit: int = FEEDBACK_EXAMPLES_LIMIT
) -> str:
    """Same idea as feedback_examples_context, for company leads (Phase 15) - a separate function
    rather than a shared/parameterized one, since the two feedback vocabularies genuinely differ
    (3-valued relevant/not_relevant/already_known here vs. 2-valued for listings) and read from a
    different table."""
    rows = db.get_company_feedback_examples(conn, limit=limit)
    if not rows:
        return ""

    labels = {
        "relevant": "RELEVANT",
        "not_relevant": "NOT RELEVANT",
        "already_known": "ALREADY KNOWN",
    }
    lines = [
        "## Feedback from past company leads",
        "The candidate has already given feedback on these company leads from earlier runs. Use "
        "it to calibrate judgement on similar companies - 'already known' means don't bother "
        "resurfacing companies like this one, not that it was a bad suggestion.",
    ]
    for row in rows:
        verdict = labels.get(row["feedback"], row["feedback"])
        line = f"- [{verdict}] {row['name']} ({row['sector']})"
        if row["feedback_note"]:
            line += f' - candidate said: "{row["feedback_note"]}"'
        lines.append(line)
    return "\n".join(lines)


def load_criteria(profile_dir: Path | str | None = None) -> Criteria:
    """Reads criteria from the DB, seeding it once from criteria.yaml if the DB is empty."""
    directory = Path(profile_dir or os.environ.get("PROFILE_DIR") or DEFAULT_PROFILE_DIR)
    criteria_path = directory / "criteria.yaml"

    with db.connect() as conn:
        data = db.get_criteria(conn)
        if data is None:
            if not criteria_path.exists():
                raise FileNotFoundError(
                    "No criteria set yet. Run the dashboard's onboarding wizard "
                    "(uv run python -m job_search_agent.webapp), or write your own "
                    f"{criteria_path} by hand if you'd rather not use the web UI."
                )
            data = yaml.safe_load(criteria_path.read_text(encoding="utf-8")) or {}
            db.save_criteria(conn, data)
        return Criteria.from_dict(data)


def load_profile(profile_dir: Path | str | None = None) -> Profile:
    directory = Path(profile_dir or os.environ.get("PROFILE_DIR") or DEFAULT_PROFILE_DIR)
    cv_path = directory / "cv.md"

    if not cv_path.exists():
        raise FileNotFoundError(
            f"{cv_path} not found. Copy profile/cv.example.md to profile/cv.md and fill it in."
        )

    cv_text = cv_path.read_text(encoding="utf-8")
    return Profile(cv_text=cv_text, criteria=load_criteria(profile_dir))


def main() -> None:
    try:
        profile = load_profile()
    except FileNotFoundError as exc:
        sys.exit(str(exc))
    print(profile.as_prompt_context())


if __name__ == "__main__":
    main()
