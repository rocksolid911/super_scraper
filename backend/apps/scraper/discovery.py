"""
On-site discovery — turn a URL into a pick-list (Phase 1-2 of the discovery roadmap).

Two capabilities behind the "what's on this site?" flow:

* ``discover_sections`` (map_site) — read the page's header/navigation and return the
  named sections a user can choose from (Reports, Blogs, Products, ...).
* ``discover_items`` (list_items) — on a chosen section/listing page, find the dominant
  group of repeating links and return them as selectable entries. The returned list
  doubles as the *live preview* of what scraping that page would yield.

Both are pure heuristics (BeautifulSoup, no LLM) so discovery stays free and fast — see
the project's cost-minimisation rule. They fetch the page once via :class:`SelectorTester`
(the same sync-friendly fetch the visual selector uses) and are called from the DRF views
with ``asyncio.run`` exactly like ``snapshot``/``infer-selectors``.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .scraping_engine import SelectorTester

logger = logging.getLogger(__name__)

# Containers we prefer to read section links from before falling back to the whole page.
_NAV_SELECTORS = [
    'header', 'nav', '[role="navigation"]',
    '.nav', '.navbar', '.menu', '.navigation', '.main-menu', '.primary-menu',
    '#nav', '#menu', '#navigation', '#main-menu',
]

# Labels that are utility/auth/legal rather than content sections.
_SKIP_LABELS = {
    'login', 'log in', 'sign in', 'signin', 'sign up', 'signup', 'register',
    'logout', 'log out', 'my account', 'account', 'cart', 'checkout', 'basket',
    'subscribe', 'newsletter', 'search', 'privacy', 'privacy policy', 'terms',
    'terms of service', 'terms & conditions', 'cookie policy', 'cookies',
    'sitemap', 'rss', 'feed', 'share', 'follow us', 'home',
}
_SKIP_LABEL_SUBSTRINGS = ('facebook', 'twitter', 'instagram', 'linkedin', 'youtube', 'whatsapp')

# Item discovery scopes to the page's main content landmark (most CMSs expose one),
# which excludes header/nav/footer/sidebars without an over-broad class filter. Listed
# most-specific first; we use the first landmark that actually holds links.
_CONTENT_SELECTORS = [
    'main', '[role="main"]', 'article',
    '#content', '#main-content', '.main-content', '.region-content',
    '.view-content', '#main', '.content',
]

# Inside the content region, still skip semantic chrome and (narrowly) pagers/breadcrumbs.
# We deliberately keep the class list tight — broad hints like "nav"/"menu" match theme
# wrappers (e.g. Bootstrap "navbar-nav") and would swallow real content.
_CHROME_TAGS = {'nav', 'header', 'footer', 'aside'}
_PAGER_CLASS_HINTS = ('pagination', 'pager', 'breadcrumb')

# Generic anchor text that isn't a usable entry label — borrow a label from the row.
_GENERIC_LABELS = {
    'view', 'view details', 'details', 'download', 'read more', 'read', 'more',
    'open', 'link', 'pdf', 'click here', 'see more', 'view all', 'go', 'here',
    '»', '›', '→', '...', '…',
}

_SECTION_LIMIT = 40
_ITEM_LIMIT = 200
_MIN_GROUP = 3


def _clean_label(text: Optional[str]) -> str:
    return re.sub(r'\s+', ' ', (text or '')).strip()


def _skip_href(href: Optional[str]) -> bool:
    """True for hrefs that don't navigate to a real page (anchors, scripts, mailto…)."""
    if not href:
        return True
    h = href.strip().lower()
    return (
        h.startswith('#')
        or h.startswith('javascript:')
        or h.startswith('mailto:')
        or h.startswith('tel:')
    )


def _offsite(url: str, base_host: str) -> bool:
    """True if ``url`` points to a different host than ``base_host``."""
    host = urlparse(url).netloc
    return bool(base_host and host and host != base_host)


def _in_chrome(tag) -> bool:
    """True if ``tag`` sits inside chrome we never want as a content entry.

    Within the already-scoped content region this only screens semantic regions
    (nested nav/aside/header/footer) and pagers/breadcrumbs — kept narrow so theme
    wrappers don't swallow real content.
    """
    parent = tag.parent
    while parent is not None and getattr(parent, 'name', None):
        if parent.name in _CHROME_TAGS:
            return True
        for cls in (parent.get('class', []) or []):
            low = cls.lower()
            if any(hint in low for hint in _PAGER_CLASS_HINTS):
                return True
        parent = parent.parent
    return False


def _content_root(soup):
    """Return the page's main content node (or ``<body>``) to search for entries.

    Picking the content landmark up front is far more reliable than trying to filter
    chrome out of the whole page: it naturally excludes the header, nav, and footer.
    """
    for sel in _CONTENT_SELECTORS:
        try:
            node = soup.select_one(sel)
        except Exception:  # noqa: BLE001 - a bad selector shouldn't kill discovery
            continue
        if node and len(node.find_all('a')) >= 3:
            return node
    return soup.body or soup


def _best_label(a) -> str:
    """Best human label for an entry link.

    Prefers the anchor's own text (or a longer title/aria-label). When that is empty
    or generic (a bare "View"/"Download"/"PDF" button), borrows a label from the
    surrounding row — a heading if present, else the row's text minus the link text.
    """
    text = _clean_label(a.get_text())
    full = _clean_label(a.get('title') or a.get('aria-label'))
    if len(full) > len(text):
        text = full
    if text and text.lower() not in _GENERIC_LABELS and len(text) >= 2:
        return text

    row = a.find_parent(['tr', 'li', 'article', 'dd'])
    if row is not None:
        heading = row.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
        if heading:
            # Listings often truncate the heading's visible text but keep the full
            # string in the inner link's title attribute — prefer it.
            inner = heading.find('a')
            htext = _clean_label((inner.get('title') if inner else None) or heading.get_text())
            if len(htext) >= 2:
                return htext[:140]
        rowtext = _clean_label(row.get_text(' '))
        if text:
            rowtext = rowtext.replace(text, ' ').strip()
        rowtext = _clean_label(rowtext)
        if len(rowtext) >= 2:
            return rowtext[:140]
    return text


def _extract_sections(html: str, base_url: str) -> List[Dict[str, str]]:
    """Heuristic nav scrape: dedup'd on-site links from the header/menu, content-only."""
    soup = BeautifulSoup(html, 'html.parser')

    anchors: list = []
    for sel in _NAV_SELECTORS:
        try:
            for node in soup.select(sel):
                anchors.extend(node.find_all('a'))
        except Exception:  # noqa: BLE001 - a bad selector shouldn't kill discovery
            continue
    if not anchors:  # No recognisable nav — scan the whole page.
        anchors = soup.find_all('a')

    base_host = urlparse(base_url).netloc
    seen_labels: set = set()
    seen_urls: set = set()
    out: List[Dict[str, str]] = []
    for a in anchors:
        href = a.get('href')
        if _skip_href(href):
            continue
        label = _clean_label(a.get_text())
        if not label or len(label) > 40:  # long text is body copy, not a nav item
            continue
        low = label.lower()
        if low in _SKIP_LABELS or any(s in low for s in _SKIP_LABEL_SUBSTRINGS):
            continue
        url = urljoin(base_url, href)
        if _offsite(url, base_host):
            continue
        if low in seen_labels or url in seen_urls:
            continue
        seen_labels.add(low)
        seen_urls.add(url)
        out.append({'label': label, 'url': url})
        if len(out) >= _SECTION_LIMIT:
            break
    return out


def _shape_key(a, depth: int = 3) -> str:
    """Signature of an anchor's ancestor chain (tag + classes), ignoring position.

    Sibling links in the same list share an identical chain, so grouping anchors by
    this key clusters a page's repeating entries together.
    """
    parts: List[str] = []
    parent = a.parent
    for _ in range(depth):
        if parent is None or not getattr(parent, 'name', None):
            break
        classes = '.'.join(sorted(parent.get('class', []) or []))
        parts.append(f"{parent.name}.{classes}")
        parent = parent.parent
    return '>'.join(parts)


def _extract_items(html: str, base_url: str) -> List[Dict[str, str]]:
    """Find the dominant group of repeating content links on a listing page."""
    soup = BeautifulSoup(html, 'html.parser')
    base_host = urlparse(base_url).netloc
    root = _content_root(soup)

    groups: Dict[str, List[Dict[str, str]]] = {}
    for a in root.find_all('a'):
        href = a.get('href')
        if _skip_href(href):
            continue
        if _in_chrome(a):
            continue
        url = urljoin(base_url, href)
        if _offsite(url, base_host):
            continue
        label = _best_label(a)
        if len(label) < 2:
            continue
        groups.setdefault(_shape_key(a), []).append({'title': label, 'url': url})

    if not groups:
        return []

    # The largest similarly-shaped group is the page's main listing. If nothing
    # repeats clearly, fall back to every on-site content link, flattened.
    best = max(groups.values(), key=len)
    if len(best) < _MIN_GROUP:
        best = [item for group in groups.values() for item in group]

    seen: set = set()
    out: List[Dict[str, str]] = []
    for item in best:
        if item['url'] in seen:
            continue
        seen.add(item['url'])
        out.append(item)
        if len(out) >= _ITEM_LIMIT:
            break
    return out


async def discover_sections(
    url: str, *, use_js_rendering: bool = False, timeout: int = 30
) -> Dict[str, Any]:
    """Map a site's header/navigation into a list of named sections to choose from."""
    html = await SelectorTester.fetch_html(url, use_js_rendering=use_js_rendering)
    if not html:
        return {'success': False, 'error': 'Failed to fetch page', 'url': url, 'sections': []}
    sections = _extract_sections(html, url)
    return {'success': True, 'url': url, 'sections': sections, 'total': len(sections)}


async def discover_items(
    url: str, *, use_js_rendering: bool = False, timeout: int = 30
) -> Dict[str, Any]:
    """Enumerate the repeating entries on a section/listing page (also the preview)."""
    html = await SelectorTester.fetch_html(url, use_js_rendering=use_js_rendering)
    if not html:
        return {'success': False, 'error': 'Failed to fetch page', 'url': url, 'items': []}
    items = _extract_items(html, url)
    return {'success': True, 'url': url, 'items': items, 'total': len(items)}
