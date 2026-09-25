"""Results page: matched listings grouped by Sonnet's score bucket, with enough info to decide
without opening the link.
"""

import json

from flask import Blueprint, render_template

from job_search_agent import db

results_bp = Blueprint("results", __name__)

_STATUS_LABELS = {
    "sonnet_strong": "Strong matches",
    "sonnet_possible": "Possible matches",
    "sonnet_weak": "Weak matches",
}


@results_bp.route("/")
def index():
    with db.connect() as conn:
        groups = {}
        for status, label in _STATUS_LABELS.items():
            rows = conn.execute(
                """
                SELECT listings.*, verdicts.detail_json
                FROM listings
                LEFT JOIN verdicts
                    ON verdicts.listing_id = listings.id AND verdicts.stage = 'sonnet'
                WHERE listings.status = ?
                ORDER BY CAST(verdicts.verdict AS INTEGER) DESC
                """,
                (status,),
            ).fetchall()
            listings = []
            for row in rows:
                detail = json.loads(row["detail_json"]) if row["detail_json"] else {}
                listings.append({**dict(row), **detail})
            groups[label] = listings

        stats = {
            "total": conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0],
            "filtered": conn.execute(
                "SELECT COUNT(*) FROM listings WHERE status = 'filtered'"
            ).fetchone()[0],
            "haiku_no": conn.execute(
                "SELECT COUNT(*) FROM listings WHERE status = 'haiku_no'"
            ).fetchone()[0],
            "pending": conn.execute(
                "SELECT COUNT(*) FROM listings WHERE status = 'pending_fit'"
            ).fetchone()[0],
        }

    return render_template("results.html", groups=groups, stats=stats)
