"""Companies-to-watch dashboard page (Phase 15) - reads from company_leads, entirely separate
from the job-listings pages. Grouped by feedback state, all on one unpaginated page: this pipeline
runs on a far less frequent schedule than job listings (see companies.py), so realistic volume
doesn't need the pagination/multi-view treatment webapp/results.py needed for listings.
"""

from flask import Blueprint, abort, render_template, request

from job_search_agent import db
from job_search_agent.webapp.results import _redirect_with_saved

companies_bp = Blueprint("companies", __name__)

VALID_FEEDBACK = {"relevant", "not_relevant", "already_known"}

_GROUP_LABELS = {
    None: "To review",
    "relevant": "Marked relevant",
    "already_known": "Already known",
    "not_relevant": "Not relevant",
}


def _fetch(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM company_leads ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]


def _group(leads: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {label: [] for label in _GROUP_LABELS.values()}
    for lead in leads:
        groups[_GROUP_LABELS.get(lead["feedback"], "To review")].append(lead)
    return groups


@companies_bp.route("/companies")
def index():
    with db.connect() as conn:
        leads = _fetch(conn)
        groups = _group(leads)
    return render_template(
        "companies.html",
        groups=groups,
        total=len(leads),
        saved_id=request.args.get("saved", type=int),
    )


@companies_bp.route("/companies/feedback/<int:company_id>", methods=["POST"])
def give_feedback(company_id):
    feedback = request.form.get("feedback") or None
    note = request.form.get("note", "").strip() or None
    if feedback and feedback not in VALID_FEEDBACK:
        abort(400)
    with db.connect() as conn:
        if feedback:
            db.set_company_feedback(conn, company_id, feedback, note)
        else:
            db.set_company_note(conn, company_id, note)
    return _redirect_with_saved(request.form.get("next"), company_id, default_endpoint="companies.index")
