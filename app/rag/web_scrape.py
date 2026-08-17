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
from typing import Optional
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from app.config import SCRAPER_USER_AGENT

HEADERS = {"User-Agent": SCRAPER_USER_AGENT}
_TIMEOUT_SECONDS = 20
# Short on purpose: robots.txt is an advisory pre-check (see
# robots_disallows), so it must never dominate the time an ingest takes.
_ROBOTS_TIMEOUT_SECONDS = 5


class ScrapeError(ValueError):
    """Raised for any fetch/parse failure -- callers turn this into a 400."""


def robots_disallows(url: str) -> Optional[str]:
    """A human-readable reason if `url`'s own robots.txt disallows fetching
    it with this app's User-Agent, else None.

    F-002. This app's own seeder (scripts/seed_knowledge_base.py) already
    declines to crawl pyscf.org because its robots.txt disallows AI agents
    -- and then the KB's URL-fetch feature, which shares neither that code
    nor that check, ingested 11 pages from exactly that site. One half of
    the app respected a site's stated wishes while the other half did not
    even look.

    Deliberately advisory rather than a hard block: this is a single
    operator-initiated fetch of a page they chose, not a crawl, and there
    are legitimate cases (a site whose robots.txt blocks everything by
    accident, a page the operator has separate permission for). The route
    surfaces the reason and lets the human decide, which is the same
    "never silently resolve an ambiguity" discipline this codebase applies
    elsewhere. It fails open on any error reading robots.txt -- an
    unreachable or malformed robots.txt is not consent, but it is also not
    a refusal, and blocking on it would make the feature hostage to an
    unrelated network hiccup.
    """
    try:
        parts = urlsplit(url)
        robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
        resp = requests.get(robots_url, headers=HEADERS, timeout=_ROBOTS_TIMEOUT_SECONDS)
        if resp.status_code != 200 or not resp.text.strip():
            return None
        parser = RobotFileParser()
        parser.parse(resp.text.splitlines())
        if not parser.can_fetch(HEADERS["User-Agent"], url):
            return (
                f"{parts.netloc}'s robots.txt disallows automated fetching of this path "
                f"for this app's User-Agent."
            )
        # Cloudflare's Content-Signal convention, which is what pyscf.org
        # actually uses and what the seeder honours -- robotparser does not
        # model it, so it is matched textually.
        if re.search(r"(?im)^\s*Content-Signal\s*:.*ai-train\s*=\s*no", resp.text):
            return (
                f"{parts.netloc}'s robots.txt carries `Content-Signal: ai-train=no`, "
                f"asking that its content not be used for AI training or ingestion."
            )
    except Exception:
        return None
    return None


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
