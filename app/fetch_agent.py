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


_SEARCH_HOSTS = ("duckduckgo.com", "bing.com", "google.com", "search.yahoo", "search.brave")


def _is_search_page(url: str) -> bool:
    u = (url or "").lower()
    return any(h in u for h in _SEARCH_HOSTS)


def _first_content_link(links: list[str], url: str) -> str | None:
    """From a search-results page, return the first link that is NOT the
    search engine itself (so we actually leave the results page)."""
    if not _is_search_page(url):
        return None
    for u in links:
        lu = u.lower()
        if any(h in lu for h in _SEARCH_HOSTS):
            continue
        if lu.startswith("javascript:") or lu.startswith("#") or lu.startswith("mailto:"):
            continue
        if lu.endswith(("png", "jpg", "jpeg", "gif", "svg", "css", "js")):
            continue
        return u
    return None


def _search_url(task: str) -> str:
    from urllib.parse import quote

    # Primary: DuckDuckGo Lite (lightest, most datacenter-friendly HTML).
    return f"https://lite.duckduckgo.com/lite/?q={quote(task)}"


def _search_fallbacks(task: str) -> list[str]:
    from urllib.parse import quote

    q = quote(task)
    return [
        f"https://lite.duckduckgo.com/lite/?q={q}",
        f"https://html.duckduckgo.com/html/?q={q}",
        f"https://www.bing.com/search?q={q}",
    ]


_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


def _fetch(url: str, timeout: float = 30.0) -> str:
    r = httpx.get(url, follow_redirects=True, timeout=timeout, headers={"User-Agent": _UA})
    return r.text


def _fetch_search(task: str) -> tuple[str, str]:
    """Try each search engine until one responds. Returns (html, url_used)."""
    last_err = None
    for u in _search_fallbacks(task):
        try:
            return _fetch(u), u
        except httpx.HTTPError as e:
            last_err = e
            continue
    raise httpx.HTTPError(f"all search engines failed (last: {last_err})")


_SYSTEM = (
    "You are a web-research agent. You receive the visible text of a web page "
    "and a user task. Respond ONLY with JSON.\n"
    "To KEEP browsing: {\"done\": false, \"answer\": \"\", \"next_url\": \"<full http(s) URL from the page>\"}\n"
    "To FINISH: {\"done\": true, \"answer\": \"<concise answer to the task>\", \"next_url\": \"\"}\n"
    "Rules:\n"
    "- If the current page already contains enough information to answer, set done:true with the answer. DO NOT keep browsing a content page you already understand.\n"
    "- If you are on a search-results page, pick the single most relevant result link as next_url.\n"
    "- Only set next_url to a real http(s) link shown on the page. Never invent URLs.\n"
    "- Prefer content pages (articles, docs, product pages) over more search pages.\n"
    "- Once you reach ANY content page that is on-topic, answer from it rather than drilling deeper.\n"
    "- Keep answers short and factual; cite the source URL if useful.\n"
    "- You MUST answer by step 3 at the latest if the page is relevant — do not loop."
)


def run(task: str, start_url: str | None = None, max_steps: int = 8) -> dict:
    visited: set[str] = set()
    url = start_url
    is_search = url is None  # first step is a search when no explicit URL
    last_text = ""
    best_page = {"text": "", "url": "", "score": 0}
    fetch_failures = 0

    def _score(text: str, u: str) -> int:
        s = len(text)
        low = (u or "").lower()
        # search-result pages are poor answer sources
        if any(k in low for k in ("/search", "duckduckgo", "bing.com/search", "google.com/search")):
            s = 0
        return s

    for step in range(max_steps):
        if url and url in visited:
            break
        try:
            if is_search:
                html, url = _fetch_search(task)
                is_search = False
            else:
                html = _fetch(url)
        except httpx.HTTPError as e:
            fetch_failures += 1
            if fetch_failures >= 3 or not visited:
                return {"result": f"Failed to fetch {url or 'search'}: {e}", "steps": step + 1}
            # skip this page, try to continue from a search next time
            url = None
            is_search = True
            continue
        visited.add(url)
        text = extract.extract_text(html, url) or ""
        last_text = text
        sc = _score(text, url)
        if sc > best_page["score"]:
            best_page = {"text": text, "url": url, "score": sc}
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
        if not nxt and _is_search_page(url):
            # LLM didn't pick a result -> follow the first real content link
            fb = _first_content_link(links, url)
            if fb:
                nxt = fb
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
    # Step limit reached without an answer: synthesize from the best content page.
    if best_page["text"]:
        try:
            summary = chat(
                "You are a research summarizer. Given a web page and a user task, "
                "return a concise, factual answer (2-4 sentences) drawn ONLY from the page. "
                "Cite the source URL if useful. If the page does not address the task, say so briefly.",
                f"TASK: {task}\nSOURCE: {best_page['url']}\nPAGE TEXT:\n{best_page['text'][:6000]}",
            )
            if summary and summary.strip():
                return {"result": summary.strip(), "steps": max_steps, "note": "summarized from best page"}
        except Exception:
            pass
    return {
        "result": f"Reached step limit ({max_steps}) without a final answer. "
                  f"Last URL: {url}",
        "steps": max_steps,
    }
