"""NIRA Browser Service — a 512MB-friendly agentic web browser.

Default backend (`fetch`) reads page text via httpx + an LLM agent loop
(no Chromium). Optional `playwright` backend uses browser-use when Chromium
is available (local/desktop or a larger instance).
"""

__all__ = ["llm", "extract", "fetch_agent", "playwright_backend", "agent", "api"]
