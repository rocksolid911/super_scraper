"""
Engine selection + fallback.

``get_engine`` returns a provider by name. ``fetch_with_fallback`` renders a URL
with the primary engine (Crawl4AI) and transparently retries with Firecrawl when
the primary returns nothing and Firecrawl is configured.
"""
from __future__ import annotations

import logging
from typing import Optional

from .base import BaseEngine, FetchResult
from .crawl4ai_engine import Crawl4AIEngine

logger = logging.getLogger(__name__)


def get_engine(name: str = "crawl4ai", **kwargs) -> BaseEngine:
    if name == "crawl4ai":
        return Crawl4AIEngine(**kwargs)
    if name == "firecrawl":
        from .firecrawl_engine import FirecrawlEngine
        return FirecrawlEngine(**kwargs)
    raise ValueError(f"Unknown engine: {name}")


def get_fetch_engine(**kwargs) -> BaseEngine:
    """Return the default fetch/render engine."""
    return get_engine("crawl4ai", **kwargs)


async def fetch_with_fallback(
    primary: BaseEngine,
    url: str,
    *,
    js: bool = True,
    timeout: int = 30,
    wait_for: Optional[str] = None,
) -> FetchResult:
    """Fetch with the primary engine; fall back to Firecrawl on empty/failed result."""
    result = await primary.fetch(url, js=js, timeout=timeout, wait_for=wait_for)
    if result.success and not result.is_empty:
        return result

    from .firecrawl_engine import FirecrawlEngine
    if FirecrawlEngine.is_available():
        logger.info(f"Falling back to Firecrawl for {url}")
        fallback = FirecrawlEngine()
        try:
            return await fallback.fetch(url, js=js, timeout=timeout)
        finally:
            await fallback.close()
    return result
