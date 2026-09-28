"""Builds the User-Agent string sent to external job sites/APIs.

Centralised here so every source agent identifies itself the same way, and so nobody else
running this project accidentally sends the original author's contact details instead of their
own.
"""

import os
import sys
from importlib.metadata import version

from dotenv import load_dotenv

from job_search_agent.env_utils import ENV_PATH


def build_user_agent() -> str:
    # Explicit path - see claude_client.require_api_key for why bare load_dotenv() isn't safe
    # under every deployment (mod_wsgi in particular).
    load_dotenv(ENV_PATH)
    contact_email = os.environ.get("CONTACT_EMAIL")
    if not contact_email:
        sys.exit(
            "CONTACT_EMAIL is not set. Copy .env.example to .env and set CONTACT_EMAIL to your "
            "own email address - it's sent as contact info in the User-Agent header to external "
            "job sites, so it needs to be yours, not whoever wrote this code."
        )
    return f"job-search-agent/{version('job-search-agent')} (personal project; contact {contact_email})"
