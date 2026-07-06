"""
Change alerts (Monitoring bundle).

Notify configured channels when a run's scraped content changed. Channels live on
``ScrapeJob.notify_config`` as::

    {"channels": [{"type": "slack"|"discord"|"webhook"|"email",
                   "target": "<url or email>", "label": "..."}]}

Slack/Discord/webhook are HTTP POSTs (reusing the same outbound pattern as the webhook
destination); email goes through Django's configured mail backend. Delivery failures
never fail the run — each channel's result is returned and recorded on the run stats.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_TIMEOUT = 10


def build_message(job, run, change: Dict[str, Any]) -> str:
    """Human-readable one-liner summarising what changed."""
    run_id = getattr(run, 'id', None)
    added = change.get('added', 0)
    removed = change.get('removed', 0)
    unchanged = change.get('unchanged', 0)
    where = f" Run #{run_id}." if run_id else ""
    approx = " Counts are approximate (row cap exceeded)." if change.get('truncated') else ""
    return (
        f"[super_scraper] '{job.name}' changed: "
        f"+{added} added, -{removed} removed ({unchanged} unchanged).{where}{approx}"
    )


def _post_json(url: str, payload: dict) -> None:
    import requests

    resp = requests.post(url, json=payload, timeout=_TIMEOUT)
    resp.raise_for_status()


def _send_channel(channel: Dict[str, Any], message: str, job, run, change) -> Dict[str, Any]:
    ctype = (channel.get('type') or '').lower()
    target = channel.get('target') or channel.get('url') or channel.get('email')
    label = channel.get('label') or ctype
    try:
        if not target:
            raise ValueError("channel has no target")
        if ctype == 'slack':
            _post_json(target, {'text': message})
        elif ctype == 'discord':
            _post_json(target, {'content': message})
        elif ctype == 'webhook':
            _post_json(target, {
                'event': 'change_detected',
                'job': {'id': job.id, 'name': job.name},
                'run_id': getattr(run, 'id', None),
                'change': change,
                'message': message,
            })
        elif ctype == 'email':
            from django.conf import settings
            from django.core.mail import send_mail

            from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or 'noreply@super-scraper.local'
            send_mail(
                subject=f"[super_scraper] '{job.name}' changed",
                message=message,
                from_email=from_email,
                recipient_list=[target],
                fail_silently=False,
            )
        else:
            raise ValueError(f"unknown channel type: {ctype}")
        return {'type': ctype, 'label': label, 'success': True}
    except Exception as e:  # noqa: BLE001 - report per-channel, never raise
        logger.warning(f"Alert channel '{ctype}' failed for job {getattr(job, 'id', '?')}: {e}")
        return {'type': ctype, 'label': label, 'success': False, 'error': str(e)}


def send_change_alert(job, run, change: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Deliver a change alert to every channel configured on the job."""
    channels = (job.notify_config or {}).get('channels', [])
    if not channels:
        return []
    message = build_message(job, run, change)
    return [_send_channel(c, message, job, run, change) for c in channels]
