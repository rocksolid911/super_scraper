"""
LangGraph scraping agent.

Flow::

    plan ──> harvest ──┐
              ▲         │ (more URLs and under caps?)
              └─────────┘
                        │ else
                        ▼
                       END

* **plan** — fetch the first page, ask the LLM for an ``ExtractionPlan`` (columns,
  whether it's a list, optional CSS selectors, whether to follow detail links).
* **harvest** — pop a URL; if it's an *index* page and we're following detail links,
  collect detail URLs via CSS and enqueue them; otherwise LLM-extract rows from the
  page markdown. Loops until URLs are exhausted or the step/item caps are hit.

``run_agent`` is a synchronous wrapper (the Celery task calls it via the engine's
event loop) returning ``{rows, plan, steps, visited, errors}``.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Type
from urllib.parse import urljoin

from pydantic import BaseModel, create_model

from ..engines.registry import fetch_with_fallback
from .llm import get_llm
from .state import ExtractionPlan, ScrapeState, safe_field_name

logger = logging.getLogger(__name__)

MAX_MARKDOWN_CHARS = 18000

_ANGLE_URL_RE = re.compile(r'<([^>\s]+)>')


def _truncate(text: str, limit: int = MAX_MARKDOWN_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + "\n... (truncated)"


def clean_url_value(value: str, base_url: str) -> str:
    """Normalise a URL the LLM lifted from markdown into an absolute, unwrapped URL.

    Handles the two generic failure modes of LLM link extraction: markdown autolink
    wrapping (``<...>``) and relative hrefs. Non-URL strings pass through unchanged.
    """
    v = value.strip()
    m = _ANGLE_URL_RE.search(v)
    if m and '/' in m.group(1):  # e.g. "https://site/x/</x/page.php?id=1>"
        return urljoin(base_url, m.group(1))
    if v.startswith('/') and ' ' not in v:  # bare relative path
        return urljoin(base_url, v)
    return value


def absolutize_row_urls(row: Dict[str, Any], base_url: str) -> Dict[str, Any]:
    """Clean any URL-shaped string values in an extracted row (see clean_url_value)."""
    return {
        k: (clean_url_value(v, base_url) if isinstance(v, str) else v)
        for k, v in row.items()
    }


def build_row_models(field_names: List[str]) -> Type[BaseModel]:
    """Build a dynamic ``Result`` model with one Optional[str] column per field."""
    row_fields = {name: (Optional[str], None) for name in field_names}
    RowModel = create_model('Row', **row_fields)
    ResultModel = create_model('Result', rows=(List[RowModel], ...))
    return ResultModel


# --------------------------------------------------------------------------- nodes


async def plan_node(state: ScrapeState, *, engine) -> Dict[str, Any]:
    start_urls = state['start_urls']
    first_md = ""
    if start_urls:
        fr = await fetch_with_fallback(engine, start_urls[0], js=state.get('js', True),
                                       timeout=state.get('timeout', 30))
        first_md = _truncate(fr.markdown or fr.html)

    llm = get_llm(role='planner').with_structured_output(ExtractionPlan)
    prompt = (
        "You are a web-scraping planner. Given a user's request and a sample of the "
        "page content, decide what columns to extract.\n\n"
        f"USER REQUEST:\n{state['prompt']}\n\n"
        f"PAGE SAMPLE (markdown):\n{first_md}\n\n"
        "Return a plan: snake_case field names, whether the page is a list of repeating "
        "items, best-effort CSS selectors, and whether each item has a detail page worth "
        "visiting to get the full data the user asked for."
    )
    plan: ExtractionPlan = await llm.ainvoke(prompt)

    # Sanitize field names to valid identifiers and de-duplicate.
    seen = set()
    for f in plan.fields:
        f.name = safe_field_name(f.name)
        while f.name in seen:
            f.name += "_x"
        seen.add(f.name)

    role = 'index' if (plan.is_list and plan.follow_detail_links and plan.detail_link_selector) else 'content'
    return {
        'plan': plan.model_dump(),
        'urls_to_visit': [{'url': u, 'role': role} for u in start_urls],
        'visited': [],
        'rows': [],
        'steps': 0,
        'errors': [],
    }


async def harvest_node(state: ScrapeState, *, engine) -> Dict[str, Any]:
    queue = list(state.get('urls_to_visit', []))
    visited = list(state.get('visited', []))
    rows = list(state.get('rows', []))
    errors = list(state.get('errors', []))
    plan = state['plan']
    max_items = state.get('max_items', plan.get('max_items', 200))

    entry = queue.pop(0)
    url, role = entry['url'], entry['role']
    if url in visited:
        return {'urls_to_visit': queue}
    visited.append(url)

    try:
        if role == 'index':
            # Collect detail-page links from the index, enqueue them as content pages.
            link_schema = {
                'container': plan.get('container_selector'),
                'fields': {'__link__': {
                    'selector': plan.get('detail_link_selector') or 'a',
                    'attr': 'href', 'type': 'url',
                }},
            }
            link_rows = await engine.extract_css(url, link_schema, js=state.get('js', True),
                                                 timeout=state.get('timeout', 30))
            enqueued = 0
            for r in link_rows:
                href = r.get('__link__')
                if not href:
                    continue
                abs_url = urljoin(url, href)
                if abs_url not in visited and enqueued < max_items:
                    queue.append({'url': abs_url, 'role': 'content'})
                    enqueued += 1
            logger.info(f"[agent] index {url}: enqueued {enqueued} detail pages")
        else:
            fr = await fetch_with_fallback(engine, url, js=state.get('js', True),
                                           timeout=state.get('timeout', 30))
            if not fr.success or fr.is_empty:
                errors.append(f"fetch failed: {url}: {fr.error}")
            else:
                field_names = [f['name'] for f in plan['fields']]
                ResultModel = build_row_models(field_names)
                llm = get_llm(role='extractor').with_structured_output(ResultModel)
                col_desc = "\n".join(f"- {f['name']}: {f['description']}" for f in plan['fields'])
                ext_prompt = (
                    "Extract structured rows from the page content below.\n\n"
                    f"USER REQUEST:\n{state['prompt']}\n\n"
                    f"COLUMNS:\n{col_desc}\n\n"
                    f"PAGE CONTENT (markdown):\n{_truncate(fr.markdown or fr.html)}\n\n"
                    "Return every matching row. Use null for missing values. Do not invent data."
                )
                result = await llm.ainvoke(ext_prompt)
                new = [absolutize_row_urls(r.model_dump(), url) for r in result.rows]
                for row in new:
                    row['_source_url'] = url
                rows.extend(new)
                logger.info(f"[agent] content {url}: +{len(new)} rows (total {len(rows)})")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[agent] harvest error on {url}: {e}")
        errors.append(f"{url}: {e}")

    return {
        'urls_to_visit': queue,
        'visited': visited,
        'rows': rows[:max_items],
        'errors': errors,
        'steps': state.get('steps', 0) + 1,
    }


def should_continue(state: ScrapeState) -> str:
    plan = state.get('plan') or {}
    max_items = state.get('max_items', plan.get('max_items', 200))
    if not state.get('urls_to_visit'):
        return 'end'
    if state.get('steps', 0) >= state.get('max_steps', 50):
        return 'end'
    if len(state.get('rows', [])) >= max_items:
        return 'end'
    return 'continue'


# --------------------------------------------------------------------------- graph


def build_graph(engine):
    from functools import partial

    from langgraph.graph import END, StateGraph

    g = StateGraph(ScrapeState)
    g.add_node('planner', partial(plan_node, engine=engine))
    g.add_node('harvest', partial(harvest_node, engine=engine))
    g.set_entry_point('planner')
    g.add_edge('planner', 'harvest')
    g.add_conditional_edges('harvest', should_continue, {'continue': 'harvest', 'end': END})
    return g.compile()


async def _arun_agent(prompt: str, start_urls: List[str], *, max_steps: int,
                      max_items: int, js: bool, timeout: int) -> Dict[str, Any]:
    from ..engines import get_fetch_engine

    engine = get_fetch_engine()
    try:
        graph = build_graph(engine)
        initial: ScrapeState = {
            'prompt': prompt,
            'start_urls': start_urls,
            'max_steps': max_steps,
            'max_items': max_items,
            'js': js,
            'timeout': timeout,
        }
        final = await graph.ainvoke(initial, config={'recursion_limit': max_steps + 10})
        return {
            'rows': final.get('rows', []),
            'plan': final.get('plan', {}),
            'steps': final.get('steps', 0),
            'visited': final.get('visited', []),
            'errors': final.get('errors', []),
        }
    finally:
        await engine.close()


def run_agent(prompt: str, start_urls: List[str], *, max_steps: int = 50,
              max_items: int = 200, js: bool = True, timeout: int = 30) -> Dict[str, Any]:
    """Synchronous entry point for the Celery task."""
    return asyncio.run(_arun_agent(
        prompt, start_urls, max_steps=max_steps, max_items=max_items, js=js, timeout=timeout))
