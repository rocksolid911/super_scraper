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


def _discover_next_url(html: str, current_url: str) -> Optional[str]:
    """Find the next-page URL of a paginated list (rel=next, "next" anchors,
    page-param increment) — same heuristics the CSS path uses."""
    from ..scraping_engine import ScrapingEngine
    try:
        return ScrapingEngine().discover_next_url(html, current_url)
    except Exception as e:  # noqa: BLE001 - pagination is best-effort
        logger.warning(f"[agent] next-page discovery failed on {current_url}: {e}")
        return None


# --------------------------------------------------------------------------- nodes


async def plan_node(state: ScrapeState, *, engine) -> Dict[str, Any]:
    start_urls = state['start_urls']
    first_md = ""
    page_cache: Dict[str, Any] = {}
    errors: List[str] = []
    for u in start_urls:
        fr = await fetch_with_fallback(engine, u, js=state.get('js', True),
                                       timeout=state.get('timeout', 30))
        if fr.success and not fr.is_empty:
            first_md = _truncate(fr.markdown or fr.html)
            page_cache[u] = fr  # harvest reuses this instead of re-fetching
            break
        errors.append(f"fetch failed: {u}: {fr.error}")

    if not first_md:
        # Nothing fetched — planning on an empty sample would only hallucinate
        # columns and waste an LLM call. End the run with the fetch errors.
        return {
            'plan': {},
            'urls_to_visit': [],
            'visited': [],
            'rows': [],
            'steps': 0,
            'errors': errors or ['no start URLs provided'],
        }

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
        'page_cache': page_cache,
        'rows': [],
        'steps': 0,
        'errors': errors,
    }


async def harvest_node(state: ScrapeState, *, engine) -> Dict[str, Any]:
    queue = list(state.get('urls_to_visit', []))
    visited = list(state.get('visited', []))
    rows = list(state.get('rows', []))
    errors = list(state.get('errors', []))
    plan = state['plan']
    max_items = state.get('max_items', plan.get('max_items', 200))

    if not queue:  # the planner may bail without enqueueing anything
        return {'urls_to_visit': queue}

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
            # The planner already fetched the first page — reuse its result
            # instead of paying a second (possibly minute-long) fetch.
            fr = (state.get('page_cache') or {}).get(url)
            if fr is None:
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

                def _row_key(r):
                    return tuple(sorted(
                        (k, v) for k, v in r.items() if k != '_source_url'
                    ))
                seen_keys = {_row_key(r) for r in rows}
                fresh = [r for r in new if _row_key(r) not in seen_keys]

                rows.extend(new)
                logger.info(f"[agent] content {url}: +{len(new)} rows (total {len(rows)})")

                # Paginate list pages: enqueue the next page while under the step
                # budget. Only when this page yielded rows we hadn't seen — a page
                # of repeats or an empty page means the "next" heuristic walked
                # past the end of the real list (each page costs an LLM call).
                if plan.get('is_list') and fresh and fr.html:
                    next_url = _discover_next_url(fr.html, url)
                    if (next_url and next_url not in visited
                            and all(q['url'] != next_url for q in queue)):
                        queue.append({'url': next_url, 'role': 'content'})
                        logger.info(f"[agent] pagination: enqueued {next_url}")
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
