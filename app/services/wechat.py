"""
WeChat public account article fetching service.

Provides utilities to fetch WeChat article text by URL, search for public
accounts via Sogou Weixin, retrieve recent articles from an account, and
process manually pasted content.
"""

import re
import html
import urllib.parse
from html.parser import HTMLParser

import httpx

from ..config import HEADERS

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SOGOU_SEARCH_URL = "https://weixin.sogou.com/weixin"
SOGOU_ARTICLE_URL = "https://weixin.sogou.com/weixin"

# Timeout for all HTTP requests (seconds)
_REQUEST_TIMEOUT = 30.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    """Minimal HTML parser that accumulates visible text and optionally
    extracts content only within a target ``<div>``."""

    def __init__(self, target_attrs: dict | None = None,
                 target_id: str | None = None,
                 target_class: str | None = None):
        super().__init__(convert_charrefs=True)
        self._target_id = target_id
        self._target_class = target_class
        self._target_attrs = target_attrs
        self._depth = 0            # nesting depth inside target div (0 = outside)
        self._capture = False
        self._parts: list[str] = []

    # -- HTMLParser overrides ----------------------------------------------

    def handle_starttag(self, tag, attrs):
        attr_dict = {k: v for k, v in attrs}
        if self._matches_target(tag, attr_dict):
            self._capture = True
            self._depth += 1
            return

        if self._capture:
            # Track nesting of any tag inside target
            if tag == "div":
                self._depth += 1
            # Insert whitespace for block-level elements
            if tag in ("p", "br", "div", "section", "h1", "h2", "h3",
                       "h4", "h5", "h6", "li", "tr"):
                self._parts.append("\n")

    def handle_endtag(self, tag):
        if self._capture and tag == "div":
            self._depth -= 1
            if self._depth <= 0:
                self._capture = False
                self._depth = 0

    def handle_data(self, data):
        if self._capture:
            self._parts.append(data)

    # -- helpers -----------------------------------------------------------

    def _matches_target(self, tag: str, attrs: dict) -> bool:
        if tag != "div":
            return False
        if self._target_id and attrs.get("id") == self._target_id:
            return True
        cls = attrs.get("class", "") or ""
        if self._target_class and self._target_class in cls.split():
            return True
        if self._target_attrs:
            return all(attrs.get(k) == v for k, v in self._target_attrs.items())
        return False

    def get_text(self) -> str:
        raw = "".join(self._parts)
        # Decode entities (convert_charrefs handles most, but double-check)
        raw = html.unescape(raw)
        # Collapse whitespace
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def _strip_tags(html_fragment: str) -> str:
    """Strip HTML tags from a fragment and decode entities."""
    text = re.sub(r"<[^>]+>", "", html_fragment)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_title(full_html: str) -> str:
    """Extract the ``<title>`` or og:title from raw HTML."""
    m = re.search(r'<meta\s+property="og:title"\s+content="([^"]*)"', full_html, re.I)
    if m:
        return html.unescape(m.group(1)).strip()
    m = re.search(r"<title[^>]*>(.*?)</title>", full_html, re.I | re.S)
    if m:
        return html.unescape(m.group(1)).strip()
    return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_article_text(url: str) -> str:
    """Fetch a WeChat (mp.weixin.qq.com) article and return plain text.

    Extraction order:
      1. ``<div id="js_content">``
      2. ``<div class="rich_media_content">``
      3. Fallback: ``<div class="rich_media_area_primary">``

    If none match, return the page's visible text (best-effort).
    """
    headers = {**HEADERS, "Accept": "text/html,application/xhtml+xml"}
    with httpx.Client(timeout=_REQUEST_TIMEOUT, follow_redirects=True) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        page_html = resp.text

    # Try js_content first
    for target_id, target_class in [
        ("js_content", None),
        (None, "rich_media_content"),
        (None, "rich_media_area_primary"),
    ]:
        extractor = _TextExtractor(target_id=target_id, target_class=target_class)
        try:
            extractor.feed(page_html)
        except Exception:
            continue
        text = extractor.get_text()
        if text and len(text) > 50:
            return text

    # Last-ditch: strip all tags
    return _strip_tags(page_html)


def search_account(keyword: str) -> list[dict]:
    """Search for WeChat public accounts via Sogou Weixin.

    Returns a list of dicts:
        ``{name, biz, url, description}``

    Sogou may return anti-crawl pages; on any failure an empty list is returned.
    """
    encoded = urllib.parse.quote(keyword)
    search_url = f"{SOGOU_SEARCH_URL}?type=1&query={encoded}"
    headers = {
        **HEADERS,
        "Referer": "https://weixin.sogou.com/",
    }

    try:
        with httpx.Client(timeout=_REQUEST_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(search_url, headers=headers)
            # Sogou returns 302/anti-spam when blocked
            if resp.status_code != 200:
                return []
            page = resp.text
    except Exception:
        return []

    results: list[dict] = []

    # Each account result is inside a <div class="news-box"> or
    # <div class="gzh-box2"> depending on Sogou layout variation.
    # We try both patterns.

    # Pattern 1: gzh-box2 (accounts)
    account_blocks = re.findall(
        r'<div\s+class="gzh-box2"[^>]*>(.*?)</div>\s*</div>',
        page, re.S
    )

    for block in account_blocks:
        try:
            name_m = re.search(
                r'<a[^>]*class="tit"[^>]*>(.*?)</a>', block, re.S
            )
            if not name_m:
                name_m = re.search(r'<a[^>]*>(.*?)</a>', block, re.S)
            name = _strip_tags(name_m.group(1)) if name_m else ""

            url_m = re.search(r'href="([^"]*)"', block)
            url = url_m.group(1) if url_m else ""
            if url and not url.startswith("http"):
                url = urllib.parse.urljoin("https://weixin.sogou.com", url)

            # Extract biz parameter from URL
            biz = ""
            biz_m = re.search(r'[?&]biz=([^&"]+)', url)
            if not biz_m:
                biz_m = re.search(r'biz["\s:=]+([A-Za-z0-9_-]+)', block)
            biz = biz_m.group(1) if biz_m else ""

            desc = ""
            desc_m = re.search(
                r'<span\s+class="info"[^>]*>(.*?)</span>', block, re.S
            )
            if desc_m:
                desc = _strip_tags(desc_m.group(1))
            if not desc:
                desc_m = re.search(r'<p[^>]*class="txt-info"[^>]*>(.*?)</p>', block, re.S)
                if desc_m:
                    desc = _strip_tags(desc_m.group(1))

            if name:
                results.append({
                    "name": name,
                    "biz": biz,
                    "url": url,
                    "description": desc,
                })
        except Exception:
            continue

    # Pattern 2: news-list2 (accounts, alternate layout)
    if not results:
        account_blocks = re.findall(
            r'<div\s+class="news-list2"[^>]*>(.*?)</div>\s*</div>',
            page, re.S
        )
        for block in account_blocks:
            try:
                name_m = re.search(
                    r'<a[^>]*target="_blank"[^>]*>(.*?)</a>', block, re.S
                )
                name = _strip_tags(name_m.group(1)) if name_m else ""

                url_m = re.search(r'href="([^"]*)"', block)
                url = url_m.group(1) if url_m else ""
                if url and not url.startswith("http"):
                    url = urllib.parse.urljoin("https://weixin.sogou.com", url)

                biz = ""
                biz_m = re.search(r'[?&]biz=([^&"]+)', url)
                if biz_m:
                    biz = biz_m.group(1)

                desc = ""
                desc_m = re.search(r'<p\s+class="txt-info"[^>]*>(.*?)</p>', block, re.S)
                if desc_m:
                    desc = _strip_tags(desc_m.group(1))

                if name:
                    results.append({
                        "name": name,
                        "biz": biz,
                        "url": url,
                        "description": desc,
                    })
            except Exception:
                continue

    return results


def get_recent_articles(biz: str) -> list[dict]:
    """Get recent articles from a WeChat public account via Sogou.

    Args:
        biz: The Biz ID of the public account (e.g. ``"MzA3MDMyNzMzNw=="``).

    Returns a list of dicts:
        ``{title, url, pub_date, summary}``
    """
    if not biz:
        return []

    # Sogou article search by account biz
    search_url = (
        f"{SOGOU_ARTICLE_URL}?type=2&query=&biz={urllib.parse.quote(biz)}"
    )
    headers = {**HEADERS, "Referer": "https://weixin.sogou.com/"}

    try:
        with httpx.Client(timeout=_REQUEST_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(search_url, headers=headers)
            if resp.status_code != 200:
                return []
            page = resp.text
    except Exception:
        return []

    articles: list[dict] = []

    # Sogou article results are inside <div class="news-box"> elements
    article_blocks = re.findall(
        r'<div\s+class="news-box"[^>]*>(.*?)</div>\s*<!--\s*end\s*news-box',
        page, re.S
    )
    if not article_blocks:
        article_blocks = re.findall(
            r'<div\s+class="txt-box"[^>]*>(.*?)</div>\s*</div>', page, re.S
        )

    for block in article_blocks:
        try:
            # Title
            title_m = re.search(
                r'<a[^>]*target="_blank"[^>]*>(.*?)</a>', block, re.S
            )
            title = _strip_tags(title_m.group(1)) if title_m else ""

            # URL
            url_m = re.search(r'href="([^"]*)"', block)
            url = url_m.group(1) if url_m else ""
            if url and not url.startswith("http"):
                url = urllib.parse.urljoin("https://weixin.sogou.com", url)

            # Publication date — Sogou shows it in a span/script
            pub_date = ""
            date_m = re.search(r'(\d{4}-\d{2}-\d{2})', block)
            if not date_m:
                date_m = re.search(r'timeConvert\("(\d+)"\)', block)
                if date_m:
                    import datetime
                    ts = int(date_m.group(1))
                    pub_date = datetime.datetime.fromtimestamp(
                        ts
                    ).strftime("%Y-%m-%d")
            else:
                pub_date = date_m.group(1)

            # Summary
            summary = ""
            sum_m = re.search(
                r'<p\s+class="txt-info"[^>]*>(.*?)</p>', block, re.S
            )
            if sum_m:
                summary = _strip_tags(sum_m.group(1))

            if title:
                articles.append({
                    "title": title,
                    "url": url,
                    "pub_date": pub_date,
                    "summary": summary,
                })
        except Exception:
            continue

    return articles


def manual_paste(url: str, raw_text: str | None = None) -> dict:
    """Process manually pasted article content.

    If *raw_text* is provided, use it directly. Otherwise, fetch the article
    text from *url* via :func:`fetch_article_text`.

    Returns:
        ``{title, text, word_count, url}``
    """
    if raw_text:
        text = raw_text.strip()
    elif url:
        text = fetch_article_text(url)
    else:
        text = ""

    # Attempt to extract a title from the first non-empty line
    title = ""
    if text:
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped:
                title = stripped
                break

    # If we couldn't get a title from text, try fetching the page <title>
    if not title and url:
        try:
            with httpx.Client(timeout=_REQUEST_TIMEOUT, follow_redirects=True) as client:
                resp = client.get(url, headers=HEADERS)
                resp.raise_for_status()
                title = _extract_title(resp.text)
        except Exception:
            pass

    word_count = len(text.split()) if text else 0

    return {
        "title": title,
        "text": text,
        "word_count": word_count,
        "url": url or "",
    }
