"""Extract readable text from raw HTML (trafilatura, bs4 fallback)."""
from __future__ import annotations

import bs4
import trafilatura


def extract_text(html: str, url: str = "") -> str:
    """Return main article text, capped to keep token usage sane for 512MB."""
    txt = None
    try:
        txt = trafilatura.extract(html, url=url)
    except Exception:
        txt = None
    if not txt:
        try:
            soup = bs4.BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
                tag.decompose()
            txt = soup.get_text("\n")
        except Exception:
            txt = html
    lines = [ln.strip() for ln in (txt or "").splitlines() if ln.strip()]
    return "\n".join(lines)[:12000]
