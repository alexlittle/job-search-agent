"""Results, system-excluded, user-rejected, and hidden pages, all built from the same
listing-fetch helper so a listing's feedback controls work identically everywhere.

Every listing falls into exactly one of five buckets - hidden first, then feedback, then system
status:
- hidden_at is set                                         -> hidden, always, regardless of anything
- feedback = 'not_relevant'                                 -> rejected
- feedback = 'relevant'                                     -> main
- feedback is unset AND status is strong/possible           -> main (the system's own picks)
- feedback is unset AND status is filtered/haiku_no/weak    -> excluded (the system's own rejects)
- feedback is unset AND status is anything earlier in the pipeline -> pending (not scored yet)

The WHERE-clause constants below are the single source of truth for this partition - both the
pages and the homepage stats are built from them, so the two can't silently drift apart (they
did once already: an earlier version counted "excluded" without excluding what had also been
rejected, so the two numbers double-counted the overlap and didn't sum to the total).
"""

import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from flask import Blueprint, abort, redirect, render_template, request, url_for

from job_search_agent import db

results_bp = Blueprint("results", __name__)

VALID_FEEDBACK = {"relevant", "not_relevant"}
PAGE_SIZE = 25

_MAIN_STATUS_LABELS = {
    "sonnet_strong": "Strong matches",
    "sonnet_possible": "Possible matches",
}
_EXCLUDED_STATUS_LABELS = {
    "sonnet_weak": "Weak Sonnet score",
    "haiku_no": "Ruled out by the first pass",
    "filtered": "Filtered out (rule-based)",
}

HIDDEN_WHERE = "hidden_at IS NOT NULL"
MAIN_WHERE = (
    "hidden_at IS NULL AND ("
    "feedback = 'relevant' OR (feedback IS NULL AND status IN ('sonnet_strong', 'sonnet_possible'))"
    ")"
)
EXCLUDED_WHERE = (
    "hidden_at IS NULL AND feedback IS NULL "
    "AND status IN ('sonnet_weak', 'haiku_no', 'filtered')"
)
REJECTED_WHERE = "hidden_at IS NULL AND feedback = 'not_relevant'"
PENDING_WHERE = (
    "hidden_at IS NULL AND feedback IS NULL "
    # sonnet_uncertain (Phase 14) is a listing awaiting fit/retry.py's one attempt at a fuller
    # description before it's finalized into a real bucket - "not fully assessed yet", same as
    # the other statuses here.
    "AND status IN ('new', 'pending_fit', 'haiku_yes', 'haiku_maybe', 'sonnet_uncertain')"
)


def _fetch(conn, where_sql: str, page: int | None = None) -> list[dict]:
    limit_sql = f" LIMIT {PAGE_SIZE} OFFSET {(page - 1) * PAGE_SIZE}" if page else ""
    rows = conn.execute(
        f"""
        SELECT listings.*,
               haiku.reason AS haiku_reason,
               sonnet.detail_json AS sonnet_detail_json
        FROM listings
        LEFT JOIN verdicts haiku ON haiku.listing_id = listings.id AND haiku.stage = 'haiku'
        -- A listing can have more than one 'sonnet'-stage verdict if fit/retry.py (Phase 14)
        -- rescored it after fetching the full posting page - the verdicts table keeps both for
        -- history, so this picks only the newest one rather than joining every row (which would
        -- otherwise duplicate that listing in every list here).
        LEFT JOIN verdicts sonnet ON sonnet.id = (
            SELECT v.id FROM verdicts v
            WHERE v.listing_id = listings.id AND v.stage = 'sonnet'
            ORDER BY v.created_at DESC, v.id DESC LIMIT 1
        )
        WHERE {where_sql}
        ORDER BY listings.id DESC
        {limit_sql}
        """
    ).fetchall()
    listings = []
    for row in rows:
        detail = json.loads(row["sonnet_detail_json"]) if row["sonnet_detail_json"] else {}
        listings.append({**dict(row), **detail})
    return listings


def _count(conn, where_sql: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM listings WHERE {where_sql}").fetchone()[0]


def _group(listings: list[dict], labels: dict[str, str], fallback_label: str | None = None):
    """Groups by status -> label. Anything whose status isn't in `labels` (e.g. a listing marked
    relevant despite the pipeline excluding it, so it's on the main page with a non-main status)
    goes in `fallback_label` if given, instead of silently vanishing from the page."""
    groups: dict[str, list[dict]] = {label: [] for label in labels.values()}
    for listing in listings:
        label = labels.get(listing["status"], fallback_label)
        if label:
            groups.setdefault(label, []).append(listing)
    return groups


def _current_page() -> int:
    return request.args.get("page", 1, type=int)


def _redirect_with_saved(next_url: str | None, listing_id: int):
    parts = urlsplit(next_url or url_for("results.index"))
    query = dict(parse_qsl(parts.query))
    query["saved"] = str(listing_id)
    return redirect(
        urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    )


@results_bp.route("/")
def index():
    with db.connect() as conn:
        listings = _fetch(conn, MAIN_WHERE)
        groups = _group(listings, _MAIN_STATUS_LABELS, fallback_label="Your picks (marked relevant)")
        for group in groups.values():
            group.sort(key=lambda l: l.get("score", 0), reverse=True)

        stats = {
            "total": conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0],
            "shown": len(listings),
            "excluded": _count(conn, EXCLUDED_WHERE),
            "rejected": _count(conn, REJECTED_WHERE),
            "hidden": _count(conn, HIDDEN_WHERE),
            "pending": _count(conn, PENDING_WHERE),
        }

    return render_template(
        "results.html", groups=groups, stats=stats, saved_id=request.args.get("saved", type=int)
    )


@results_bp.route("/excluded")
def excluded():
    page = _current_page()
    with db.connect() as conn:
        listings = _fetch(conn, EXCLUDED_WHERE, page=page)
        total = _count(conn, EXCLUDED_WHERE)
    return render_template(
        "listing_table.html",
        title="Excluded by the Pipeline",
        intro=(
            "Listings the system itself ruled out, at whichever stage - the rule-based "
            "pre-filter, Haiku's coarse first pass, or a weak Sonnet score. Mark one "
            "“Relevant” and it moves to your results; “Hide” removes it "
            "from every view without judging it either way."
        ),
        listings=listings,
        status_labels=_EXCLUDED_STATUS_LABELS,
        page=page,
        total_pages=-(-total // PAGE_SIZE) or 1,
        saved_id=request.args.get("saved", type=int),
    )


@results_bp.route("/rejected")
def rejected():
    page = _current_page()
    with db.connect() as conn:
        listings = _fetch(conn, REJECTED_WHERE, page=page)
        total = _count(conn, REJECTED_WHERE)
    return render_template(
        "listing_table.html",
        title="Listings You've Rejected",
        intro="Everything you've marked not relevant, with your notes if you added any.",
        listings=listings,
        status_labels={},
        page=page,
        total_pages=-(-total // PAGE_SIZE) or 1,
        saved_id=request.args.get("saved", type=int),
    )


@results_bp.route("/hidden")
def hidden():
    page = _current_page()
    with db.connect() as conn:
        listings = _fetch(conn, HIDDEN_WHERE, page=page)
        total = _count(conn, HIDDEN_WHERE)
    return render_template(
        "listing_table.html",
        title="Hidden Listings",
        intro=(
            "Listings you've removed from every view. They stay in the database so they won't "
            "be re-fetched, but won't otherwise be shown anywhere until unhidden."
        ),
        listings=listings,
        status_labels={},
        page=page,
        total_pages=-(-total // PAGE_SIZE) or 1,
        saved_id=request.args.get("saved", type=int),
    )


@results_bp.route("/feedback/<int:listing_id>", methods=["POST"])
def give_feedback(listing_id):
    feedback = request.form.get("feedback") or None
    note = request.form.get("note", "").strip() or None
    if feedback and feedback not in VALID_FEEDBACK:
        abort(400)
    with db.connect() as conn:
        if feedback:
            db.set_feedback(conn, listing_id, feedback, note)
        else:
            db.set_note(conn, listing_id, note)
    return _redirect_with_saved(request.form.get("next"), listing_id)


@results_bp.route("/hide/<int:listing_id>", methods=["POST"])
def hide_listing(listing_id):
    with db.connect() as conn:
        db.set_hidden(conn, listing_id, True)
    return _redirect_with_saved(request.form.get("next"), listing_id)


@results_bp.route("/unhide/<int:listing_id>", methods=["POST"])
def unhide_listing(listing_id):
    with db.connect() as conn:
        db.set_hidden(conn, listing_id, False)
    return _redirect_with_saved(request.form.get("next"), listing_id)
