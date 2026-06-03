"""
Crawl4AI-backed engine — the default, self-hosted provider.

Uses a single ``AsyncWebCrawler`` (one Playwright browser) for the lifetime of the
engine instance, so an agent run that fetches many pages reuses one browser.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from django.conf import settings

from .base import BaseEngine, FetchResult, internal_to_crawl4ai_schema

logger = logging.getLogger(__name__)


class Crawl4AIEngine(BaseEngine):
    name = "crawl4ai"

    def __init__(self, user_agent: Optional[str] = None, headless: Optional[bool] = None):
        from crawl4ai import BrowserConfig

        cfg = settings.SCRAPER_CONFIG
        self._browser_config = BrowserConfig(
            headless=cfg['HEADLESS_BROWSER'] if headless is None else headless,
            user_agent=user_agent or cfg['DEFAULT_USER_AGENT'],
            verbose=False,
        )
        self._crawler = None

    async def _get_crawler(self):
        from crawl4ai import AsyncWebCrawler

        if self._crawler is None:
            self._crawler = AsyncWebCrawler(config=self._browser_config)
            await self._crawler.start()
        return self._crawler

    def _run_config(self, *, timeout: int, wait_for: Optional[str] = None,
                    extraction_strategy=None, scan_full_page: bool = True):
        from crawl4ai import CacheMode, CrawlerRunConfig

        # Wait only for domcontentloaded (not networkidle, which can hang on heavy
        # pages). ``scan_full_page`` auto-scrolls to trigger lazy/infinite-scroll
        # content and is ON for real runs so no rows are missed; the quick preview
        # turns it off for speed since it only samples the first page.
        return CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            page_timeout=timeout * 1000,
            wait_until='domcontentloaded',
            wait_for=wait_for,
            scan_full_page=scan_full_page,
            remove_overlay_elements=True,
            extraction_strategy=extraction_strategy,
        )

    async def fetch(
        self,
        url: str,
        *,
        js: bool = True,
        timeout: int = 30,
        wait_for: Optional[str] = None,
        scan_full_page: bool = True,
    ) -> FetchResult:
        try:
            crawler = await self._get_crawler()
            result = await crawler.arun(
                url=url,
                config=self._run_config(timeout=timeout, wait_for=wait_for,
                                        scan_full_page=scan_full_page),
            )
            links = []
            try:
                internal = (result.links or {}).get('internal', [])
                links = [l.get('href') for l in internal if l.get('href')]
            except Exception:
                pass
            return FetchResult(
                url=url,
                html=result.html or "",
                markdown=str(result.markdown or ""),
                success=bool(result.success),
                status_code=getattr(result, 'status_code', None),
                error=getattr(result, 'error_message', '') or "",
                engine=self.name,
                links=links,
            )
        except Exception as e:  # noqa: BLE001 - report, let caller decide on fallback
            logger.warning(f"Crawl4AI fetch failed for {url}: {e}")
            return FetchResult(url=url, success=False, error=str(e), engine=self.name)

    async def extract_css(
        self,
        url: str,
        selectors: Dict[str, Any],
        *,
        js: bool = True,
        timeout: int = 30,
    ) -> List[Dict[str, Any]]:
        from crawl4ai import JsonCssExtractionStrategy

        schema = internal_to_crawl4ai_schema(selectors)
        strategy = JsonCssExtractionStrategy(schema)
        crawler = await self._get_crawler()
        result = await crawler.arun(
            url=url,
            config=self._run_config(timeout=timeout, extraction_strategy=strategy),
        )
        if result.success and result.extracted_content:
            try:
                rows = json.loads(result.extracted_content)
                return rows if isinstance(rows, list) else [rows]
            except json.JSONDecodeError:
                logger.warning(f"Crawl4AI returned non-JSON extracted_content for {url}")
        return []

    async def close(self) -> None:
        if self._crawler is not None:
            try:
                await self._crawler.close()
            finally:
                self._crawler = None
