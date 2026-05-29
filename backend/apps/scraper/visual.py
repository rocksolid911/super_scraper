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


def infer_container(field_selectors: List[str]) -> Optional[str]:
    """
    Infer a repeating-item container selector from per-field selectors.

    Strategy: take the longest common ancestor chain shared by all field selectors,
    then generalize its last token (drop ``:nth-of-type``) so it matches every
    sibling item. Returns ``None`` when the fields share no meaningful ancestor
    (single-item page).
    """
    if len(field_selectors) < 1:
        return None

    token_lists = [_tokens(s) for s in field_selectors]
    common: List[str] = []
    for group in zip(*token_lists):
        if all(t == group[0] for t in group):
            common.append(group[0])
        else:
            break

    # Drop trailing tokens that are identical to a full field selector (a field that
    # is itself the common ancestor isn't a container).
    if not common:
        return None
    if len(common) == min(len(t) for t in token_lists):
        # All fields share the entire path -> they're the same element; step up one.
        common = common[:-1]
        if not common:
            return None

    container_tokens = common[:-1] + [_strip_nth(common[-1])]
    return ' > '.join(container_tokens)


def build_selectors(
    fields: List[Dict[str, Any]],
    container: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build the internal ``selectors`` config from clicked field definitions.

    ``fields`` items: ``{name, selector, attr?, type?}``. When ``container`` is set (or
    inferred), each field selector is rewritten relative to the container.
    """
    if container is None:
        container = infer_container([f['selector'] for f in fields])

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
