"""Converts an uploaded CV file (PDF/DOCX/plain text) into clean Markdown, for onboarding's
CV-upload step. Extraction is local/free; only the reformatting step calls Claude.

Doesn't work on scanned/image-only PDFs (no OCR) - if extraction finds no text, it says so
rather than silently producing an empty/garbage CV.

Run with: uv run python -m job_search_agent.cv_import <path-to-cv-file>
"""

import asyncio
import io
import sys
from pathlib import Path

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query

from job_search_agent.claude_client import anthropic_env

MODEL = "claude-sonnet-5"


def extract_text(filename: str, raw_bytes: bytes) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if lower.endswith(".docx"):
        import docx

        document = docx.Document(io.BytesIO(raw_bytes))
        return "\n".join(p.text for p in document.paragraphs)
    return raw_bytes.decode("utf-8", errors="ignore")


def build_prompt(raw_text: str) -> str:
    return (
        "Convert the following raw CV/resume text into clean, well-structured Markdown. Use "
        "headings for whatever sections are actually present (Professional Summary, Key Skills, "
        "Professional Experience, Education, etc.), bullet points for achievements, and bold for "
        "job titles/companies. Preserve all factual content exactly (dates, companies, numbers, "
        "achievements) - do not invent, embellish, or omit anything. Fix obvious extraction "
        "artifacts (broken line wraps, stray repeated characters) but don't change the "
        "substance.\n\n"
        "Return ONLY the markdown content, with no commentary before or after it.\n\n"
        "--- RAW CV TEXT ---\n"
        f"{raw_text}"
    )


async def convert_to_markdown(filename: str, raw_bytes: bytes) -> tuple[str, float]:
    """Returns (markdown, cost_usd)."""
    raw_text = extract_text(filename, raw_bytes)
    if not raw_text.strip():
        raise ValueError(
            f"Couldn't extract any text from {filename!r}. If it's a scanned/image-based PDF "
            "(no selectable text), this won't work - try a text-based export instead."
        )

    options = ClaudeAgentOptions(
        model=MODEL,
        max_turns=1,
        tools=[],
        env=anthropic_env(),
    )

    markdown = ""
    cost_usd = 0.0
    async for message in query(prompt=build_prompt(raw_text), options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    markdown += block.text
        elif isinstance(message, ResultMessage):
            cost_usd = message.total_cost_usd or 0.0
    return markdown.strip(), cost_usd


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: uv run python -m job_search_agent.cv_import <path-to-cv-file>")
    path = Path(sys.argv[1])
    markdown, cost_usd = asyncio.run(convert_to_markdown(path.name, path.read_bytes()))
    print(markdown)
    print(f"\n[${cost_usd:.4f} cost]", file=sys.stderr)


if __name__ == "__main__":
    main()
