"""Fetch-based agentic browser — no Chromium, fits 512MB.

The LLM drives a loop of: read page text -> decide to answer or follow a link.
Each fetch is a plain HTTP GET (httpx); we parse <a href> links, let the LLM
pick the next one, and stop when it answers or hits max steps.
"""
from __future__ import annotations

import json
import re

import httpx

from . import extract
from .llm import chat

_LINK_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)


def _links(html: str, base: str) -> list[str]:
    out: list[str] = []
    for m in _LINK_RE.finditer(html):
        href = m.group(1)
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("javascript:"):
            continue
        if href.startswith("/"):
            from urllib.parse import urljoin

            href = urljoin(base, href)
        if href.startswith("http"):
            out.append(href)
    # de-dup preserving order
    seen = set()
    uniq = []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq[:40]


_SYSTEM = (
    "You are a web-browsing agent. You receive the text of a web page and a "
    "user task. Respond ONLY with JSON: "
    '{"done": false, "answer": "", "next_url": "<full url or empty>"} to keep '
    'browsing, or {"done": true, "answer": "<your final answer>", "next_url": ""} '
    "to finish. Only set next_url to an http(s) link present on the page that "
    "helps the task. Never invent URLs."
)


def run(task: str, start_url: str, max_steps: int = 6) -> dict:
    visited = set()
    url = start_url
    for step in range(max_steps):
        if url in visited:
            break
        visited.add(url)
        try:
            r = httpx.get(url, follow_redirects=True, timeout=20,
                          headers={"User-Agent": "NIRABrowser/1.0"})
            html = r.text
        except httpx.HTTPError as e:
            return {"result": f"Failed to fetch {url}: {e}", "steps": step + 1}
        text = extract.extract_text(html, url)
        links = _links(html, url)
        prompt = (
            f"USER TASK: {task}\n\nCURRENT URL: {url}\n\nPAGE TEXT:\n{text}\n\n"
            f"AVAILABLE LINKS (pick one if needed):\n" + "\n".join(links)
        )
        try:
            raw = chat(_SYSTEM, prompt)
        except Exception as e:  # LLM failure -> surface it
            return {"result": f"LLM error: {e}", "steps": step + 1}
        # tolerate fenced json
        raw_clean = raw.strip().strip("`").lstrip("json").strip()
        try:
            decision = json.loads(raw_clean)
        except json.JSONDecodeError:
            decision = {"done": True, "answer": raw[:1500], "next_url": ""}
        if decision.get("done") or not decision.get("next_url"):
            return {"result": decision.get("answer") or raw[:1500], "steps": step + 1}
        url = decision["next_url"]
    return {"result": f"Reached step limit ({max_steps}) without a final answer. Last URL: {url}", "steps": max_steps}
