"""Loads the user's CV + job-search criteria into a single context block for the agents.

The CV lives in profile/cv.md (gitignored) - see profile/cv.example.md for the format.
Criteria live in the database (Phase 8 on), seeded once from profile/criteria.example.yaml's
sibling profile/criteria.yaml the first time it's needed; after that, the DB is the source of
truth and the dashboard's criteria page (not the YAML file) is how you change it.

Run with: uv run python -m job_search_agent.profile
"""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from job_search_agent import db

DEFAULT_PROFILE_DIR = Path(__file__).resolve().parents[2] / "profile"


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


def load_criteria(profile_dir: Path | str | None = None) -> Criteria:
    """Reads criteria from the DB, seeding it once from criteria.yaml if the DB is empty."""
    directory = Path(profile_dir or os.environ.get("PROFILE_DIR") or DEFAULT_PROFILE_DIR)
    criteria_path = directory / "criteria.yaml"

    with db.connect() as conn:
        data = db.get_criteria(conn)
        if data is None:
            if not criteria_path.exists():
                raise FileNotFoundError(
                    f"No criteria in the database yet, and {criteria_path} doesn't exist "
                    "either. Copy profile/criteria.example.yaml to profile/criteria.yaml and "
                    "fill it in, or set criteria via the dashboard's Criteria page."
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
