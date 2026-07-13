"""Fetch-based agentic browser — no Chromium, fits 512MB.

The LLM drives a loop of: read page text -> decide to answer or follow a link.
Each fetch is a plain HTTP GET (httpx); we parse <a href> links, let the LLM
pick the next one, and stop when it answers or hits max steps.

Search (no start URL) uses DuckDuckGo's server-rendered HTML endpoint, which
returns parseable result links — unlike Google's JS/bot-blocked results page.
"""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

from . import extract
from .llm import chat

_LINK_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)


def _resolve(href: str, base: str) -> str | None:
    """Normalise a link, resolving search-engine redirect wrappers to the
    real destination URL. Returns None for non-http/s or junk links."""
    if not href or href.startswith(("#", "mailto:", "javascript:", "data:")):
        return None
    # Google redirect: /url?q=https://real.example
    if "google.com/url" in href or href.startswith("/url?"):
        q = parse_qs(urlparse(href if href.startswith("http") else urljoin(base, href)).query)
        real = q.get("q", [None])[0]
        if real:
            return real
    # DuckDuckGo redirect: //duckduckgo.com/l/?uddg=<encoded>
    if "duckduckgo.com/l/" in href:
        q = parse_qs(urlparse(href if href.startswith("http") else urljoin(base, href)).query)
        real = q.get("uddg", [None])[0]
        if real:
            return real
    if href.startswith("//"):
        href = "https:" + href
    elif href.startswith("/"):
        href = urljoin(base, href)
    return href if href.startswith("http") else None


def _links(html: str, base: str) -> list[str]:
    out: list[str] = []
    for m in _LINK_RE.finditer(html):
        u = _resolve(m.group(1), base)
        if u:
            out.append(u)
    seen: set[str] = set()
    uniq: list[str] = []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq[:40]


def _search_url(task: str) -> str:
    from urllib.parse import quote

    return f"https://html.duckduckgo.com/html/?q={quote(task)}"


_SYSTEM = (
    "You are a web-research agent. You receive the visible text of a web page "
    "and a user task. Respond ONLY with JSON.\n"
    "To KEEP browsing: {\"done\": false, \"answer\": \"\", \"next_url\": \"<full http(s) URL from the page>\"}\n"
    "To FINISH: {\"done\": true, \"answer\": \"<concise answer to the task>\", \"next_url\": \"\"}\n"
    "Rules:\n"
    "- If the current page already contains enough information to answer, set done:true with the answer.\n"
    "- If you are on a search-results page, pick the single most relevant result link as next_url.\n"
    "- Only set next_url to a real http(s) link shown on the page. Never invent URLs.\n"
    "- Prefer content pages (articles, docs, product pages) over more search pages.\n"
    "- Keep answers short and factual; cite the source URL if useful."
)


def run(task: str, start_url: str | None = None, max_steps: int = 8) -> dict:
    visited: set[str] = set()
    url = start_url or _search_url(task)
    last_text = ""
    for step in range(max_steps):
        if url in visited:
            break
        visited.add(url)
        try:
            r = httpx.get(url, follow_redirects=True, timeout=20,
                          headers={"User-Agent": "Mozilla/5.0 (compatible; NIRABrowser/1.0)"})
            html = r.text
        except httpx.HTTPError as e:
            return {"result": f"Failed to fetch {url}: {e}", "steps": step + 1}
        text = extract.extract_text(html, url) or ""
        last_text = text
        links = _links(html, url)
        prompt = (
            f"USER TASK: {task}\n\nCURRENT URL: {url}\n\nPAGE TEXT:\n{text[:6000]}\n\n"
            f"AVAILABLE LINKS (pick one if needed):\n" + "\n".join(links)
        )
        try:
            raw = chat(_SYSTEM, prompt)
        except Exception as e:  # LLM failure -> surface it
            return {"result": f"LLM error: {e}", "steps": step + 1}
        raw_clean = raw.strip().strip("`").lstrip("json").strip()
        try:
            decision = json.loads(raw_clean)
        except json.JSONDecodeError:
            decision = {"done": True, "answer": raw[:1500], "next_url": ""}
        answer = (decision.get("answer") or "").strip()
        nxt = decision.get("next_url") or ""
        nxt = _resolve(nxt, url) if nxt else ""
        if decision.get("done") and answer:
            return {"result": answer, "steps": step + 1}
        if nxt:
            url = nxt
            continue
        # No next link and not done -> stop, return whatever we have
        if answer:
            return {"result": answer, "steps": step + 1}
        return {
            "result": f"Could not find a definitive answer after visiting {len(visited)} page(s). "
                      f"Last page had {len(text)} chars of text.",
            "steps": step + 1,
        }
    return {
        "result": f"Reached step limit ({max_steps}) without a final answer. "
                  f"Last URL: {url}",
        "steps": max_steps,
    }
