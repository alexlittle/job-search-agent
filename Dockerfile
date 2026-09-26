# Runs the dashboard by default (uv run python -m job_search_agent.webapp) - see
# docker-compose.yml for the volumes this needs (.env, data/, profile/) and how to run the
# coordinator/companies pipelines as one-off commands against the same persistent state instead.
FROM python:3.12-slim

# Installing uv this way (rather than pip installing it) matches the pinned version used
# elsewhere in this project's tooling and avoids a slower `pip install uv` + its own dependency
# resolution just to get the tool that does dependency resolution.
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first, cached separately from application code - most rebuilds during development
# only change source files, not pyproject.toml/uv.lock, so this layer is reused.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .
RUN uv sync --frozen

EXPOSE 5000
ENV HOST=0.0.0.0
ENV FLASK_DEBUG=false

CMD ["uv", "run", "python", "-m", "job_search_agent.webapp"]
