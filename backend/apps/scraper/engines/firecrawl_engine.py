"""
Firecrawl-backed engine — managed fallback for JS-heavy / anti-bot / blocked sites.

Only usable when ``FIRECRAWL_API_KEY`` is configured. The registry falls back to
this engine when Crawl4AI returns nothing for a domain.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from django.conf import settings

from .base import BaseEngine, FetchResult

logger = logging.getLogger(__name__)


class FirecrawlEngine(BaseEngine):
    name = "firecrawl"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or getattr(settings, 'FIRECRAWL_API_KEY', '')
        if not self.api_key:
            raise ValueError("FIRECRAWL_API_KEY is not configured")
        self._app = None

    @classmethod
    def is_available(cls) -> bool:
        return bool(getattr(settings, 'FIRECRAWL_API_KEY', ''))

    def _get_app(self):
        from firecrawl import FirecrawlApp

        if self._app is None:
            self._app = FirecrawlApp(api_key=self.api_key)
        return self._app

    async def fetch(
        self,
        url: str,
        *,
        js: bool = True,
        timeout: int = 30,
        wait_for: Optional[str] = None,
    ) -> FetchResult:
        import asyncio

        def _scrape():
            app = self._get_app()
            return app.scrape_url(url, params={"formats": ["markdown", "html"]})

        try:
            data = await asyncio.to_thread(_scrape)
            return FetchResult(
                url=url,
                html=data.get('html', '') or "",
                markdown=data.get('markdown', '') or "",
                success=True,
                engine=self.name,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Firecrawl fetch failed for {url}: {e}")
            return FetchResult(url=url, success=False, error=str(e), engine=self.name)

    async def extract_css(
        self,
        url: str,
        selectors: Dict[str, Any],
        *,
        js: bool = True,
        timeout: int = 30,
    ) -> List[Dict[str, Any]]:
        # Firecrawl does not do CSS-selector extraction; CSS re-runs always use
        # Crawl4AI. This path is intentionally unsupported.
        raise NotImplementedError("FirecrawlEngine does not support CSS extraction")
