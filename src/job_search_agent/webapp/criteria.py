"""Criteria editing page: view/update job-search criteria without touching the YAML file or
the database directly. This is what makes criteria "dynamically updatable" (see docs/brief.md
follow-up decisions after Phase 4) - editing profile/criteria.yaml no longer has any effect
once the DB has been seeded from it.
"""

from flask import Blueprint, redirect, render_template, request, url_for

from job_search_agent import db
from job_search_agent.profile import Criteria, load_criteria

criteria_bp = Blueprint("criteria", __name__)


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def criteria_dict_from_form(form) -> dict:
    """Shared with onboarding's criteria step (webapp/onboarding.py) - same fields, same shape."""
    minimum = form.get("salary_minimum", "").strip()
    return {
        "roles": _lines(form.get("roles", "")),
        "locations": _lines(form.get("locations", "")),
        "salary": {
            "currency": form.get("salary_currency", "").strip() or None,
            "minimum": float(minimum) if minimum else None,
        },
        "must_haves": _lines(form.get("must_haves", "")),
        "dealbreakers": _lines(form.get("dealbreakers", "")),
        "keywords": {
            "boost": _lines(form.get("keywords_boost", "")),
            "avoid": _lines(form.get("keywords_avoid", "")),
        },
        "notes": form.get("notes", "").strip(),
    }


@criteria_bp.route("/criteria", methods=["GET", "POST"])
def edit():
    if request.method == "POST":
        data = criteria_dict_from_form(request.form)
        with db.connect() as conn:
            db.save_criteria(conn, data)
        return redirect(url_for("criteria.edit", saved=1))

    try:
        criteria = load_criteria()
    except FileNotFoundError:
        criteria = Criteria()

    return render_template("criteria.html", c=criteria, saved=request.args.get("saved"))
