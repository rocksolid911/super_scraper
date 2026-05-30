"""
Pluggable extraction engines / tools.

The LangGraph agent (``apps.scraper.agent``) and the Celery tasks call into these
engines rather than talking to Crawl4AI / Firecrawl / Playwright directly, so the
underlying provider can be swapped without touching orchestration logic.
"""
from .base import BaseEngine, FetchResult
from .registry import fetch_with_fallback, get_engine, get_fetch_engine

__all__ = [
    'BaseEngine', 'FetchResult', 'fetch_with_fallback', 'get_engine', 'get_fetch_engine',
]
