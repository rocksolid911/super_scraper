"""
Change detection for scrape runs (Monitoring bundle).

Items are deduplicated per job (``ScrapedItem.unique_together(job, unique_hash)``), so a
run only stores rows it is the *first* to see — the items table can't tell us what a
later run actually observed. To diff run-to-run we therefore record each successful
run's full content signature (the set of row hashes + short previews) on
``JobRun.content_index`` at finalization, and compare consecutive runs from that.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from apps.core.utils import generate_unique_hash

_PREVIEW_CAP = 500     # rows we keep a human-readable preview for
_HASH_CAP = 5000       # rows we track for diffing (bounds JSON size on huge jobs)
_SAMPLE = 25           # added/removed rows surfaced in the change summary


def _clean_row(data: Dict[str, Any]) -> Dict[str, Any]:
    """Drop bookkeeping keys so the hash reflects only user-facing content."""
    return {k: v for k, v in data.items() if k != '_source_url'}


def _is_empty(data: Dict[str, Any]) -> bool:
    return not any(v not in (None, '', []) for v in data.values())


def row_preview(data: Dict[str, Any], limit: int = 3, width: int = 60) -> str:
    """A compact ``k=v · k=v`` label for a row, shown in the diff view."""
    parts: List[str] = []
    for key, value in data.items():
        if value in (None, '', []):
            continue
        parts.append(f"{key}={str(value)[:width]}")
        if len(parts) >= limit:
            break
    return ' · '.join(parts)


def build_content_index(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute ``{hashes, previews, truncated}`` for every non-empty row found this run.

    Mirrors the dedup/skip logic of the task's save loop so the signature matches what
    a user would consider "the data": empty rows dropped, ``_source_url`` excluded.
    """
    hashes: List[str] = []
    previews: Dict[str, str] = {}
    seen: set = set()
    truncated = False
    for raw in items:
        if not isinstance(raw, dict):
            continue
        data = _clean_row(raw)
        if _is_empty(data):
            continue
        h = generate_unique_hash(data)
        if h in seen:
            continue
        seen.add(h)
        if len(hashes) < _HASH_CAP:
            hashes.append(h)
            if len(previews) < _PREVIEW_CAP:
                previews[h] = row_preview(data)
        else:
            truncated = True
    return {'hashes': hashes, 'previews': previews, 'truncated': truncated}


def diff_indexes(current: Dict[str, Any], previous: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Diff two content indexes into a user-facing change summary."""
    cur = set(current.get('hashes', []))
    cur_prev = current.get('previews', {})
    if not previous:
        # No prior run to compare against — this run is the baseline.
        return {
            'first_run': True, 'changed': False,
            'added': len(cur), 'removed': 0, 'unchanged': 0,
            'added_sample': [], 'removed_sample': [],
            'truncated': bool(current.get('truncated')),
        }
    prv = set(previous.get('hashes', []))
    prv_prev = previous.get('previews', {})
    added = cur - prv
    removed = prv - cur
    # If either index hit the hash cap, rows beyond it were never tracked — the
    # counts are approximate and "removed" rows may just have fallen off the cap.
    truncated = bool(current.get('truncated') or previous.get('truncated'))
    return {
        'first_run': False,
        'changed': bool(added or removed),
        'added': len(added),
        'removed': len(removed),
        'unchanged': len(cur & prv),
        'added_sample': [cur_prev[h] for h in added if h in cur_prev][:_SAMPLE],
        'removed_sample': [prv_prev[h] for h in removed if h in prv_prev][:_SAMPLE],
        'truncated': truncated,
    }


def previous_indexed_run(job, current_run):
    """Most recent finished run before ``current_run`` that carries a content index."""
    from .models import JobRun

    candidates = (
        JobRun.objects
        .filter(job=job, created_at__lt=current_run.created_at)
        .exclude(id=current_run.id)
        .order_by('-created_at')[:25]
    )
    for run in candidates:
        if (run.content_index or {}).get('hashes'):
            return run
    return None
