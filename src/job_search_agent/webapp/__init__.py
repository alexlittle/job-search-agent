"""Local Flask dashboard: view results, edit criteria, give feedback, and (later) onboard a new
user. Reads directly from the SQLite store - no separate report file. See tasks.md Phase 8.

Run with: uv run python -m job_search_agent.webapp
"""

from flask import Flask, redirect, request, url_for


def create_app() -> Flask:
    app = Flask(__name__)

    from job_search_agent.webapp.criteria import criteria_bp
    from job_search_agent.webapp.history import history_bp
    from job_search_agent.webapp.onboarding import next_incomplete_step, onboarding_bp
    from job_search_agent.webapp.results import results_bp

    app.register_blueprint(results_bp)
    app.register_blueprint(criteria_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(onboarding_bp)

    @app.before_request
    def redirect_to_onboarding_if_incomplete():
        if request.blueprint == "onboarding" or request.path.startswith("/static"):
            return None
        step = next_incomplete_step()
        if step:
            return redirect(url_for(step))
        return None

    return app
