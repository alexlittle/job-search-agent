from job_search_agent.webapp import create_app


def main() -> None:
    app = create_app()
    app.run(debug=True, port=5000)


if __name__ == "__main__":
    main()
