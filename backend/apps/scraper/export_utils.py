"""
Shared row flattening used by both file export (views) and live destinations.

Produces an ordered column list plus a list of flat row dicts from ``ScrapedItem``
records, so CSV/XLSX/JSON download and Postgres/Sheets/Webhook delivery agree on shape.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

META_COLUMNS = ['id', 'created_at', 'source_url']


def flatten_items(items: Iterable, include_meta: bool = True,
                  sample_for_columns: int = 200) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Convert ScrapedItem records into ``(columns, rows)``.

    ``columns`` is meta columns (id/created_at/source_url) followed by the union of
    data keys (sorted). Each row is a flat dict keyed by those columns.
    """
    items = list(items)

    data_keys = set()
    for item in items[:sample_for_columns]:
        if isinstance(item.data, dict):
            data_keys.update(item.data.keys())
    data_columns = sorted(data_keys)

    columns = (META_COLUMNS if include_meta else []) + data_columns

    rows: List[Dict[str, Any]] = []
    for item in items:
        row: Dict[str, Any] = {}
        if include_meta:
            row['id'] = item.id
            row['created_at'] = item.created_at.isoformat() if item.created_at else None
            row['source_url'] = item.source_url
        if isinstance(item.data, dict):
            row.update(item.data)
        rows.append(row)

    return columns, rows
