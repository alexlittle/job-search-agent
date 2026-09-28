"""WSGI entry point for running the dashboard under Apache/mod_wsgi (or any other WSGI server)
instead of `uv run python -m job_search_agent.webapp`'s Flask dev server. See
docs/apache-vhost.example.conf for a real vhost that points at this file.
"""

from job_search_agent.webapp import create_app

application = create_app()
