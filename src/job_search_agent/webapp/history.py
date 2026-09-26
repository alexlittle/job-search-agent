"""Activity/cost history page: every LLM call the pipeline has made, newest first, with its own
cost - each `cost_log` row (see db.py) already is one such call, so this page needs no extra
bookkeeping beyond what every LLM-calling module already writes via `db.log_cost()`.
"""

from flask import Blueprint, render_template, request

from job_search_agent import db

history_bp = Blueprint("history", __name__)

PAGE_SIZE = 25

STAGE_LABELS = {
    "fetch:web_search": "Web search (find listings)",
    "fit:haiku": "Haiku coarse pass",
    "fit:sonnet": "Sonnet detailed pass",
}


@history_bp.route("/history")
def index():
    page = request.args.get("page", 1, type=int)
    with db.connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM cost_log").fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM cost_log ORDER BY id DESC LIMIT ? OFFSET ?",
            (PAGE_SIZE, (page - 1) * PAGE_SIZE),
        ).fetchall()
        total_cost = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM cost_log"
        ).fetchone()[0]
        by_stage = conn.execute(
            """
            SELECT stage, COUNT(*) AS calls, SUM(cost_usd) AS cost
            FROM cost_log
            GROUP BY stage
            ORDER BY cost DESC
            """
        ).fetchall()

    return render_template(
        "history.html",
        rows=rows,
        stage_labels=STAGE_LABELS,
        total=total,
        total_cost=total_cost,
        by_stage=by_stage,
        page=page,
        total_pages=-(-total // PAGE_SIZE) or 1,
    )
