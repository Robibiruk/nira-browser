"""Facade: pick the best available backend and run a browse task."""
from __future__ import annotations

from . import fetch_agent
from .playwright_backend import available as pw_available, run as pw_run


def browse(task: str, url: str | None = None, max_steps: int = 6) -> dict:
    start = url or "https://www.google.com/search?q=" + _q(task)
    if pw_available():
        try:
            return pw_run(task, start, max_steps)
        except Exception as e:
            return {"result": f"playwright backend failed, fell back: {e}", "backend": "fetch", **fetch_agent.run(task, start, max_steps)}
    return {"backend": "fetch", **fetch_agent.run(task, start, max_steps)}


def _q(task: str) -> str:
    import urllib.parse

    return urllib.parse.quote(task)
