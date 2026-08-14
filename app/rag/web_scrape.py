"""Single-page web scraper backing the KB's "add by URL" flow.

Deliberately not a crawler like scripts/seed_knowledge_base.py's `crawl()`
-- this fetches exactly the one URL the user gives the add-source form,
same as pasting a file. Shares that script's encoding-sniff fix (a server
that omits `charset` in Content-Type makes `requests` fall back to
ISO-8859-1 per RFC 2616 even when the body is UTF-8, mangling curly
quotes/em-dashes) and its general extraction approach (strip
script/style/nav, collapse blank runs), but trimmed to what a single
arbitrary page needs rather than a known Sphinx doc site's selectors.
"""
from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; research-kb-ingest/1.0; contact: qcuser)"}
_TIMEOUT_SECONDS = 20


class ScrapeError(ValueError):
    """Raised for any fetch/parse failure -- callers turn this into a 400."""


def fetch_page(url: str) -> tuple[str, str, str]:
    """Fetches `url` and returns (title, extracted_text, raw_html).

    Raises ScrapeError with a human-readable message on any failure
    (bad scheme, network error, non-2xx status, non-HTML response) so the
    KB route can surface it directly rather than a bare traceback.
    """
    if not re.match(r"^https?://", url, re.IGNORECASE):
        raise ScrapeError("URL must start with http:// or https://")

    try:
        resp = requests.get(url, headers=HEADERS, timeout=_TIMEOUT_SECONDS)
    except requests.RequestException as e:
        raise ScrapeError(f"Could not fetch {url}: {e}") from e

    if resp.status_code != 200:
        raise ScrapeError(f"Fetching {url} returned HTTP {resp.status_code}")
    content_type = resp.headers.get("Content-Type", "")
    if "text/html" not in content_type:
        raise ScrapeError(f"{url} is not an HTML page (Content-Type: {content_type or 'unknown'})")

    if "charset" not in content_type:
        resp.encoding = resp.apparent_encoding
    html = resp.text

    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else url

    for tag in soup.select("script, style, nav, header, footer"):
        tag.decompose()
    body = soup.body or soup
    text = body.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)

    if len(text) < 50:
        raise ScrapeError(f"{url} had little or no extractable text (page may be JS-rendered)")

    return title, text, html
