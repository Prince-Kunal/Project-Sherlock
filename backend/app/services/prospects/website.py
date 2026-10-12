"""Company website text for open outreach (PLAN.md Phase 8): the homepage, the about and careers
pages, and the latest blog post when the site links one, cleaned to plain text (≤ 8k chars). The
open-outreach email's hook must quote a sentence of it (or of the company description).

Polite by construction: robots.txt is honoured for our user agent, requests go through the shared
PoliteHttpClient (≤ 1 request per second per host) with a 10 s timeout, and only HTML is read.
"""

import logging
import re
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import lxml.html
from lxml.etree import ParserError
from readability import Document

from app.services.sources.http import PoliteHttpClient, SourceHTTPError
from app.services.sources.text import html_to_text

log = logging.getLogger(__name__)

MAX_TEXT_CHARS = 8000
PAGE_CHARS = 3000  # per page, so one long page doesn't crowd out the others
ROBOTS_AGENT = "Sherlock"  # the product token of our User-Agent

_ABOUT_RE = re.compile(r"/(about|about-us|company|our-story|mission)/?$", re.I)
_CAREERS_RE = re.compile(r"/(careers?|jobs|join(-us)?|work-with-us|hiring)/?$", re.I)
_BLOG_RE = re.compile(r"/(blog|news|engineering|journal|posts)/?$", re.I)
# Layout chrome that repeats on every page.
_CHROME_RE = re.compile(r"<\s*(nav|header|footer|aside|form|svg|button)\b.*?<\s*/\s*\1\s*>", re.I | re.S)


class WebsiteFetcher:
    def __init__(self, http: PoliteHttpClient) -> None:
        """`http` should be a PoliteHttpClient with a 10 s timeout (see `website_http`)."""
        self._http = http

    async def fetch(self, domain: str) -> str | None:
        """The cleaned text of the company's site, or None if nothing could be read."""
        base = f"https://{domain}/"
        robots = await self._robots(base)
        if robots is None:
            return None
        sections: list[tuple[str, str]] = []
        home = await self._page(base, robots)
        if home is None:
            return None
        html, url = home
        sections.append(("Home", _text(html)))
        links = _links(html, url)
        about = _first(links, _ABOUT_RE) or urljoin(url, "/about")
        careers = _first(links, _CAREERS_RE) or urljoin(url, "/careers")
        for label, link in (("About", about), ("Careers", careers)):
            page = await self._page(link, robots)
            if page is not None:
                sections.append((label, _text(page[0])))
        if (blog := _first(links, _BLOG_RE)) and (index := await self._page(blog, robots)):
            post = _latest_post(_links(*index), index[1])
            if post and (page := await self._page(post, robots)):
                sections.append(("Latest blog post", _text(page[0], article=True)))
        return combine(sections)

    async def _robots(self, base: str) -> RobotFileParser | None:
        """The site's robots rules (allow-all when it has none); None when the site is unreachable."""
        parser = RobotFileParser()
        try:
            response = await self._http.get(urljoin(base, "/robots.txt"))
        except SourceHTTPError as exc:
            if exc.status is None or exc.status >= 500:
                log.info("website %s unreachable: %s", base, exc)
                return None
            # No robots.txt (404) allows everything; 401/403 on it means stay out (RFC 9309).
            parser.parse(["User-agent: *", "Disallow: /"] if exc.status in (401, 403) else [])
            return parser
        parser.parse(response.text.splitlines())
        return parser

    async def _page(self, url: str, robots: RobotFileParser) -> tuple[str, str] | None:
        """(html, final url) of an HTML page we're allowed to read, or None."""
        if not robots.can_fetch(ROBOTS_AGENT, url):
            return None
        try:
            response = await self._http.get(url, headers={"Accept": "text/html"})
        except SourceHTTPError:
            return None
        if "html" not in response.headers.get("content-type", ""):
            return None
        return response.text, str(response.url)


def website_http() -> PoliteHttpClient:
    return PoliteHttpClient(timeout_seconds=10.0, max_retries=1)


def _text(html: str, article: bool = False) -> str:
    """Readable text of a page: the main article for blog posts, otherwise the page minus its layout
    chrome (readability tends to drop most of a landing page)."""
    if article:
        try:
            text = html_to_text(Document(html).summary(), limit=PAGE_CHARS)
        except (ParserError, ValueError):
            text = ""
        if len(text) >= 200:
            return text
    return html_to_text(_CHROME_RE.sub(" ", html), limit=PAGE_CHARS)


def _links(html: str, base: str) -> list[str]:
    try:
        doc = lxml.html.fromstring(html)
    except (ParserError, ValueError):
        return []
    host = urlparse(base).hostname
    links = []
    for element in doc.iter("a"):
        href = element.get("href")
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base, href).split("#", 1)[0]
        if urlparse(absolute).hostname == host and absolute not in links:
            links.append(absolute)
    return links


def _first(links: list[str], pattern: re.Pattern[str]) -> str | None:
    return next((link for link in links if pattern.search(urlparse(link).path)), None)


def _latest_post(links: list[str], blog_url: str) -> str | None:
    """The first link on the blog index that sits below it (blog posts are usually listed newest
    first), skipping tag, category and pagination pages."""
    prefix = urlparse(blog_url).path.rstrip("/") + "/"
    for link in links:
        path = urlparse(link).path
        rest = path[len(prefix) :] if path.startswith(prefix) else ""
        if rest.strip("/") and not re.match(r"(tag|tags|category|categories|page|author)\b", rest):
            return link
    return None


def combine(sections: list[tuple[str, str]]) -> str | None:
    """Join the pages' text, dropping lines already seen on an earlier page (menus, cookie banners,
    footers that survived cleaning). Capped at 8k chars."""
    seen: set[str] = set()
    parts = []
    for label, text in sections:
        lines = []
        for line in text.splitlines():
            key = line.strip().casefold()
            if len(key) < 3 or key in seen:
                continue
            seen.add(key)
            lines.append(line.strip())
        if lines:
            parts.append(f"{label}:\n" + "\n".join(lines))
    combined = "\n\n".join(parts)[:MAX_TEXT_CHARS].strip()
    return combined or None
