"""
Engine interface shared by all extraction providers.

An engine is responsible for two low-level capabilities:

* ``fetch`` — render a URL (optionally with JS) and return HTML + markdown.
* ``extract_css`` — pull structured rows from a URL using a CSS selector schema.

Higher-level "extract this in natural language" logic lives in the LangGraph agent,
which uses these engines as tools.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class FetchResult:
    """Result of fetching/rendering a single URL."""
    url: str
    html: str = ""
    markdown: str = ""
    success: bool = True
    status_code: Optional[int] = None
    error: str = ""
    engine: str = ""
    links: List[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.html or self.markdown)


def internal_to_crawl4ai_schema(selectors: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert this project's internal selector config into a Crawl4AI
    ``JsonCssExtractionStrategy`` schema.

    Internal shape (also produced by the AI schema generator and the visual
    selector)::

        {
          "container": "css for the repeating item (or None for a single row)",
          "fields": {
            "title": {"selector": ".title", "attr": "text", "type": "string"},
            "link":  {"selector": "a",      "attr": "href", "type": "url"}
          }
        }

    Crawl4AI shape::

        {
          "name": "items",
          "baseSelector": "...",
          "fields": [{"name": "...", "selector": "...", "type": "text|attribute|html",
                      "attribute": "href"}]
        }
    """
    base_selector = selectors.get('container') or 'body'
    fields = []
    for name, cfg in (selectors.get('fields') or {}).items():
        sel = cfg.get('selector')
        if not sel:
            continue
        attr = cfg.get('attr', 'text')
        if attr == 'text':
            fields.append({"name": name, "selector": sel, "type": "text"})
        elif attr == 'html':
            fields.append({"name": name, "selector": sel, "type": "html"})
        else:
            fields.append({"name": name, "selector": sel, "type": "attribute", "attribute": attr})
    return {"name": "items", "baseSelector": base_selector, "fields": fields}


class BaseEngine(ABC):
    """Common interface for extraction engines."""

    name: str = "base"

    @abstractmethod
    async def fetch(
        self,
        url: str,
        *,
        js: bool = True,
        timeout: int = 30,
        wait_for: Optional[str] = None,
        scan_full_page: bool = True,
    ) -> FetchResult:
        """Render a URL and return its HTML + markdown.

        ``scan_full_page`` auto-scrolls to trigger lazy/infinite-scroll content;
        engines that don't support it may ignore it.
        """
        raise NotImplementedError

    @abstractmethod
    async def extract_css(
        self,
        url: str,
        selectors: Dict[str, Any],
        *,
        js: bool = True,
        timeout: int = 30,
    ) -> List[Dict[str, Any]]:
        """Extract structured rows from a URL using a CSS selector schema."""
        raise NotImplementedError

    async def close(self) -> None:
        """Release any underlying resources (browser, sessions)."""
        return None
