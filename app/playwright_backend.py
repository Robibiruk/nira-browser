"""Playwright + browser-use backend (OPT-IN, needs Chromium).

Disabled by default on 512MB/cloud. Runs only when BROWSER_BACKEND=playwright
AND a Chromium is installed (local/desktop or a >=1GB instance). If unavailable,
the facade falls back to the fetch agent.
"""
from __future__ import annotations

import os


def available() -> bool:
    if (os.getenv("BROWSER_BACKEND") or "fetch").lower() != "playwright":
        return False
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def run(task: str, start_url: str, max_steps: int = 6) -> dict:
    from browser_use import Agent
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
        temperature=0.2,
    )
    agent = Agent(task=f"{task}\nStart URL: {start_url}", llm=llm)
    history = agent.run(max_steps=max_steps)
    final = getattr(history, "final_result", lambda: None)()
    return {"result": final or str(history), "steps": max_steps}
