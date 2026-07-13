"""Minimal OpenRouter chat client (no langchain, keeps the image small).

Set LLM_MODE=mock to run offline (returns a canned JSON so the agent loop is
testable without an API key)."""
from __future__ import annotations

import os

import httpx

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def chat(system: str, user: str, *, model: str | None = None, temperature: float = 0.2) -> str:
    """Return the model's raw text response."""
    if (os.getenv("LLM_MODE") or "live").lower() == "mock":
        # Canned structured reply so the fetch-agent loop can be exercised offline.
        return (
            '{"done": true, "answer": "MOCK ANSWER (no key). Task head: '
            + user[:80].replace('"', "'")
            + '", "next_url": ""}'
        )
    model = model or os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    resp = httpx.post(
        _OPENROUTER_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]
