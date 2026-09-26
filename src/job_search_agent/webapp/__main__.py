import os

from job_search_agent.webapp import create_app


def main() -> None:
    app = create_app()
    # Bind address and debug mode are env-driven (not hardcoded) so the Docker image (Phase 16)
    # can override both without changing the local dev experience: Flask's dev server defaults to
    # 127.0.0.1, which isn't reachable from outside a container even with a port published, so the
    # image sets HOST=0.0.0.0. Debug mode's interactive debugger is a real remote-code-execution
    # risk if it's ever reachable beyond localhost, so the image also sets FLASK_DEBUG=false rather
    # than inheriting the auto-reload-friendly default meant for editing this code directly.
    host = os.environ.get("HOST", "127.0.0.1")
    debug = os.environ.get("FLASK_DEBUG", "true").lower() not in ("false", "0", "")
    app.run(host=host, debug=debug, port=5000)


if __name__ == "__main__":
    main()
