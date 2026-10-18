"""First-run setup wizard: auth mode + API key (if needed) + contact email -> .env, CV upload ->
profile/cv.md, a criteria form, and a schedule-frequency preference. Exists so someone other than
the original author can get this running without hand-editing config files - see docs/tasks.md
Phase 8 and docs/brief.md's follow-up decisions.

The schedule step only *stores* the preference; actually running on a schedule is still Phase 17.

Step 1 asks for the auth mode *first* - see claude_client.py's module docstring for what "api" vs
"claude_code" actually changes. Choosing "claude_code" here means the API key field is never
shown as required and nothing is ever written to ANTHROPIC_API_KEY - a fresh setup in that mode
has no key sitting in .env to begin with, rather than relying on it being unused-but-present.
"""

import asyncio

from flask import Blueprint, redirect, render_template, request, url_for

from job_search_agent import db
from job_search_agent.claude_client import auth_mode
from job_search_agent.cv_import import convert_to_markdown
from job_search_agent.env_utils import ENV_PATH, set_env_var
from job_search_agent.profile import DEFAULT_PROFILE_DIR, Criteria, load_criteria
from job_search_agent.webapp.criteria import criteria_dict_from_form

onboarding_bp = Blueprint("onboarding", __name__, url_prefix="/onboarding")

CV_PATH = DEFAULT_PROFILE_DIR / "cv.md"


def has_env_configured() -> bool:
    import os

    from dotenv import load_dotenv

    # Explicit path - see claude_client.require_api_key for why bare load_dotenv() isn't safe
    # under every deployment (mod_wsgi in particular).
    load_dotenv(ENV_PATH)
    if not os.environ.get("CONTACT_EMAIL"):
        return False
    # An API key is only actually required in "api" mode - claude_code mode authenticates via
    # the ambient `claude` CLI login instead, so there's nothing to check for here.
    return auth_mode() == "claude_code" or bool(os.environ.get("ANTHROPIC_API_KEY"))


def has_cv() -> bool:
    return CV_PATH.exists()


def has_criteria() -> bool:
    with db.connect() as conn:
        return db.get_criteria(conn) is not None


def next_incomplete_step() -> str | None:
    """Returns the route name of the first missing *required* step, or None if the dashboard is
    usable. The schedule preference (step 4) is part of the fresh-onboarding flow but isn't a
    hard gate - skipping or never reaching it shouldn't lock an otherwise-configured user out of
    the dashboard, since nothing else actually depends on it being set."""
    if not has_env_configured():
        return "onboarding.step1"
    if not has_cv():
        return "onboarding.step2"
    if not has_criteria():
        return "onboarding.step3"
    return None


@onboarding_bp.route("/")
def index():
    step = next_incomplete_step()
    return redirect(url_for(step) if step else "/")


@onboarding_bp.route("/step1", methods=["GET", "POST"])
def step1():
    error = None
    if request.method == "POST":
        mode = request.form.get("auth_mode", "api")
        if mode not in ("api", "claude_code"):
            mode = "api"
        contact_email = request.form.get("contact_email", "").strip()
        api_key = request.form.get("api_key", "").strip()

        if not contact_email:
            error = "Contact email is required either way - see the hint below for why."
        elif mode == "api" and not api_key:
            error = "An API key is required for Console API billing - or choose Claude Code below."
        else:
            set_env_var("LLM_AUTH_MODE", mode)
            set_env_var("CONTACT_EMAIL", contact_email)
            # Only ever written in "api" mode - a claude_code setup never gets a key put into
            # .env in the first place, rather than relying on one sitting there unused.
            if mode == "api":
                set_env_var("ANTHROPIC_API_KEY", api_key)
            return redirect(url_for("onboarding.step2"))

    return render_template("onboarding/step1.html", error=error, selected_mode=request.form.get("auth_mode", "api"))


@onboarding_bp.route("/step2", methods=["GET", "POST"])
def step2():
    error = None
    if request.method == "POST":
        uploaded = request.files.get("cv_file")
        if not uploaded or not uploaded.filename:
            error = "Please choose a file to upload."
        else:
            try:
                markdown, cost_usd = asyncio.run(
                    convert_to_markdown(uploaded.filename, uploaded.read())
                )
            except ValueError as exc:
                error = str(exc)
            else:
                DEFAULT_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
                CV_PATH.write_text(markdown, encoding="utf-8")
                with db.connect() as conn:
                    db.log_cost(
                        conn,
                        stage="onboarding:cv_import",
                        model="claude-sonnet-5",
                        num_turns=1,
                        cost_usd=cost_usd,
                        detail=uploaded.filename,
                    )
                return redirect(url_for("onboarding.step3"))
    return render_template("onboarding/step2.html", error=error)


@onboarding_bp.route("/step3", methods=["GET", "POST"])
def step3():
    if request.method == "POST":
        data = criteria_dict_from_form(request.form)
        with db.connect() as conn:
            db.save_criteria(conn, data)
        return redirect(url_for("onboarding.step4"))

    try:
        criteria = load_criteria()
    except FileNotFoundError:
        criteria = Criteria()
    return render_template("onboarding/step3.html", c=criteria)


@onboarding_bp.route("/step4", methods=["GET", "POST"])
def step4():
    if request.method == "POST":
        with db.connect() as conn:
            db.set_setting(conn, "run_frequency", request.form.get("run_frequency", "manual"))
        return redirect("/")
    return render_template("onboarding/step4.html")
