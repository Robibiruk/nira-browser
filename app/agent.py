"""Facade: pick the best available backend and run a browse task."""
from __future__ import annotations

from . import fetch_agent
from .playwright_backend import available as pw_available, run as pw_run


def browse(task: str, url: str | None = None, max_steps: int = 8) -> dict:
    # When no explicit URL is given, let the fetch backend build its own
    # (DuckDuckGo HTML) search URL — do NOT hardcode Google here.
    if pw_available():
        # Playwright can handle Google's JS results page; give it a search URL.
        start = url or "https://www.google.com/search?q=" + _q(task)
        try:
            return pw_run(task, start, max_steps)
        except Exception as e:
            return {
                "backend": "fetch",
                **fetch_agent.run(task, url, max_steps),
                "note": f"playwright backend failed, fell back: {e}",
            }
    # Fetch backend: pass url through (None -> DuckDuckGo search inside fetch_agent)
    return {"backend": "fetch", **fetch_agent.run(task, url, max_steps)}


def _q(task: str) -> str:
    import urllib.parse

    return urllib.parse.quote(task)
