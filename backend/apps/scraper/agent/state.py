"""
Agent state + structured-output schemas.

``ScrapeState`` is the LangGraph graph state. ``ExtractionPlan`` is what the planner
node emits. Per-row extraction uses a *dynamically built* Pydantic model (one field
per planned column) so structured output stays clean across providers — see
``build_row_models`` in ``graph.py``.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, TypedDict

from pydantic import BaseModel, Field


def safe_field_name(name: str) -> str:
    """Turn an arbitrary field label into a valid, snake_case identifier."""
    s = re.sub(r'[^0-9a-zA-Z]+', '_', name.strip()).strip('_').lower()
    if not s:
        s = 'field'
    if s[0].isdigit():
        s = f'f_{s}'
    return s


class FieldSpec(BaseModel):
    name: str = Field(description="snake_case column name")
    description: str = Field(description="what this column should contain")
    css_selector: Optional[str] = Field(
        default=None,
        description="best-effort CSS selector for this field relative to the item container",
    )
    attr: str = Field(default="text", description="text | html | href | src | <attribute>")


class ExtractionPlan(BaseModel):
    """The planner's output for a scraping request."""
    fields: List[FieldSpec] = Field(description="columns to extract")
    is_list: bool = Field(description="True if the page contains many repeating items")
    container_selector: Optional[str] = Field(
        default=None, description="best-effort CSS selector for the repeating item"
    )
    follow_detail_links: bool = Field(
        default=False, description="True if each item has a detail page worth visiting"
    )
    detail_link_selector: Optional[str] = Field(
        default=None, description="CSS selector for the link to an item's detail page"
    )
    max_items: int = Field(default=200, description="reasonable cap on rows to collect")


class ScrapeState(TypedDict, total=False):
    # Inputs
    prompt: str
    start_urls: List[str]
    max_steps: int
    max_items: int
    js: bool
    timeout: int

    # Working state
    urls_to_visit: List[str]
    visited: List[str]
    plan: Optional[Dict[str, Any]]      # serialized ExtractionPlan
    rows: List[Dict[str, Any]]
    steps: int
    errors: List[str]
    notes: str
