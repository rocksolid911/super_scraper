"""
Visual-selector backend.

Two capabilities used by the React click-to-select UI:

* ``snapshot`` — render a URL with Playwright and return a full-page screenshot plus
  a flat map of selectable elements (stable CSS selector + bounding box + text).
* ``infer_selectors`` — given the elements the user clicked (one per field), build the
  project's internal ``selectors`` config, inferring a repeating container when the
  fields live inside a list, and return sample rows via :class:`SelectorTester`.

The CSS selectors produced here use a consistent descendant-chain format
(``tag:nth-of-type(n) > tag:nth-of-type(n) > ...``) so container inference can operate
on the selector strings directly.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from django.conf import settings

logger = logging.getLogger(__name__)

# JS injected into the page: walk the DOM and emit a compact, selectable element map.
_DOM_MAP_JS = r"""
() => {
  const MAX = 2000;
  const TEXT_CAP = 140;

  function cssPath(el) {
    if (!(el instanceof Element)) return '';
    const parts = [];
    while (el && el.nodeType === Node.ELEMENT_NODE && el.tagName.toLowerCase() !== 'html') {
      let sel = el.tagName.toLowerCase();
      if (el.id) { sel = sel + '#' + CSS.escape(el.id); parts.unshift(sel); break; }
      let nth = 1, sib = el;
      while ((sib = sib.previousElementSibling)) {
        if (sib.tagName === el.tagName) nth++;
      }
      sel += ':nth-of-type(' + nth + ')';
      parts.unshift(sel);
      el = el.parentElement;
    }
    return parts.join(' > ');
  }

  const out = [];
  const all = document.body ? document.body.querySelectorAll('*') : [];
  for (let i = 0; i < all.length && out.length < MAX; i++) {
    const el = all[i];
    const tag = el.tagName.toLowerCase();
    if (['script', 'style', 'noscript', 'meta', 'link', 'svg', 'path'].includes(tag)) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 4 || rect.height < 4) continue;
    const text = (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, TEXT_CAP);
    const href = el.getAttribute && el.getAttribute('href');
    const src = el.getAttribute && el.getAttribute('src');
    if (!text && !href && !src) continue;
    out.push({
      selector: cssPath(el),
      tag: tag,
      text: text,
      href: href || null,
      src: src || null,
      box: {
        x: Math.round(rect.x + window.scrollX),
        y: Math.round(rect.y + window.scrollY),
        w: Math.round(rect.width),
        h: Math.round(rect.height),
      },
    });
  }
  return {
    width: document.documentElement.scrollWidth,
    height: document.documentElement.scrollHeight,
    elements: out,
  };
}
"""


async def snapshot(url: str, *, use_js_rendering: bool = True, timeout: int = 30) -> Dict[str, Any]:
    """Render ``url`` and return a screenshot path + selectable element map."""
    from playwright.async_api import async_playwright

    snap_dir = os.path.join(settings.MEDIA_ROOT, 'snapshots')
    os.makedirs(snap_dir, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.png"
    filepath = os.path.join(snap_dir, filename)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=settings.SCRAPER_CONFIG['HEADLESS_BROWSER'])
        try:
            page = await browser.new_page(user_agent=settings.SCRAPER_CONFIG['DEFAULT_USER_AGENT'])
            page.set_default_timeout(timeout * 1000)
            await page.goto(url, wait_until='networkidle')
            await page.wait_for_timeout(800)
            dom = await page.evaluate(_DOM_MAP_JS)
            await page.screenshot(path=filepath, full_page=True)
        finally:
            await browser.close()

    # Tag each element with a stable index for the frontend.
    for idx, el in enumerate(dom['elements']):
        el['id'] = idx

    return {
        'success': True,
        'url': url,
        'screenshot_url': f"{settings.MEDIA_URL}snapshots/{filename}",
        'width': dom['width'],
        'height': dom['height'],
        'elements': dom['elements'],
    }


def _tokens(selector: str) -> List[str]:
    return [t.strip() for t in selector.split('>') if t.strip()]


def _strip_nth(token: str) -> str:
    """Drop the :nth-of-type(n) qualifier so a token matches all siblings."""
    import re
    return re.sub(r':nth-of-type\(\d+\)', '', token).strip()


def _common_ancestor(field_selectors: List[str]) -> List[str]:
    """Longest common leading token chain shared by every field selector.

    Steps up one level if every field shares the entire path (they'd be the same
    element, which can't be a container). Returns ``[]`` when there's no shared
    ancestor.
    """
    if len(field_selectors) < 1:
        return []
    token_lists = [_tokens(s) for s in field_selectors]
    common: List[str] = []
    for group in zip(*token_lists):
        if all(t == group[0] for t in group):
            common.append(group[0])
        else:
            break
    if not common:
        return []
    if len(common) == min(len(t) for t in token_lists):
        common = common[:-1]
    return common


def infer_container(field_selectors: List[str]) -> Optional[str]:
    """
    Infer a repeating-item container selector from per-field selectors (string-only).

    Strategy: take the longest common ancestor chain shared by all field selectors,
    then generalize its last token (drop ``:nth-of-type``) so it matches every
    sibling item. Returns ``None`` when the fields share no meaningful ancestor
    (single-item page).

    NOTE: this guesses that the *innermost* common ancestor is the repeating unit,
    which is wrong when all fields were sampled from a single example row (the real
    repeating level is a higher ancestor — its ``:nth-of-type`` stays pinned, so the
    container matches only one row). Prefer :func:`infer_container_dom` when the page
    HTML is available; this remains the no-DOM fallback.
    """
    common = _common_ancestor(field_selectors)
    if not common:
        return None
    container_tokens = common[:-1] + [_strip_nth(common[-1])]
    return ' > '.join(container_tokens)


def infer_container_dom(
    html: str,
    field_selectors: List[str],
    min_rows: int = 2,
) -> Optional[str]:
    """
    DOM-aware container inference: pick the ancestor level that actually repeats.

    Even when every field was clicked on one example row, the row's ancestors form
    the common chain. We try generalizing each ancestor level (dropping its
    ``:nth-of-type`` and truncating there), then test the candidate against the real
    DOM. The best container is the one matching the most elements (``>= min_rows``)
    in which *every* field sub-selector still resolves — i.e. the genuine repeating
    item. Falls back to ``None`` (caller uses the string heuristic) if nothing
    repeats.
    """
    from bs4 import BeautifulSoup

    common = _common_ancestor(field_selectors)
    if not common:
        return None

    token_lists = [_tokens(s) for s in field_selectors]
    soup = BeautifulSoup(html, 'html.parser')

    best: Optional[str] = None
    best_count = 0
    # Deepest level first so ties favour the most specific (closest-to-fields) container.
    for j in range(len(common) - 1, -1, -1):
        cand_tokens = common[:j] + [_strip_nth(common[j])]
        candidate = ' > '.join(cand_tokens)
        try:
            containers = soup.select(candidate)
        except Exception:
            continue
        if len(containers) <= 1:
            continue

        # Field selectors rewritten relative to this candidate container.
        rel_selectors: List[str] = []
        usable = True
        for ft in token_lists:
            if len(ft) <= len(cand_tokens):
                usable = False
                break
            rel_selectors.append(' > '.join(ft[len(cand_tokens):]))
        if not usable:
            continue

        # Count containers where *every* field resolves -> a real, fully-populated row.
        count = 0
        for c in containers:
            if all(_safe_select_one(c, rs) for rs in rel_selectors):
                count += 1
        if count > best_count:
            best_count = count
            best = candidate

    return best if best_count >= min_rows else None


def _safe_select_one(node, selector: str) -> bool:
    """True if ``selector`` resolves to an element under ``node`` (errors -> False)."""
    if not selector:
        return False
    try:
        return node.select_one(selector) is not None
    except Exception:
        return False


def build_selectors(
    fields: List[Dict[str, Any]],
    container: Optional[str] = None,
    html: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build the internal ``selectors`` config from clicked field definitions.

    ``fields`` items: ``{name, selector, attr?, type?}``. When ``container`` is set (or
    inferred), each field selector is rewritten relative to the container. If ``html``
    is supplied and no explicit ``container`` is given, the repeating container is
    inferred against the real DOM (:func:`infer_container_dom`), falling back to the
    string-only heuristic when nothing repeats.
    """
    if container is None:
        field_sels = [f['selector'] for f in fields]
        if html:
            container = infer_container_dom(html, field_sels)
        if container is None:
            container = infer_container(field_sels)

    container_tokens = _tokens(container) if container else []

    def _matches_container(sel_tokens: List[str]) -> bool:
        n = len(container_tokens)
        if not n or len(sel_tokens) < n:
            return False
        for i in range(n):
            # The container's final token is generalized (nth stripped), so the
            # corresponding field token must be compared with nth stripped too.
            if i == n - 1:
                if _strip_nth(sel_tokens[i]) != container_tokens[i]:
                    return False
            elif sel_tokens[i] != container_tokens[i]:
                return False
        return True

    out_fields: Dict[str, Any] = {}
    for f in fields:
        name = f['name']
        sel_tokens = _tokens(f['selector'])
        if _matches_container(sel_tokens):
            rel = sel_tokens[len(container_tokens):]
            relative = ' > '.join(rel) if rel else _strip_nth(sel_tokens[-1])
        else:
            relative = f['selector']
        out_fields[name] = {
            'selector': relative,
            'attr': f.get('attr', 'text'),
            'type': f.get('type', 'string'),
        }

    return {'container': container, 'fields': out_fields}
