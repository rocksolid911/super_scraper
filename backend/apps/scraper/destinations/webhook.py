"""
POST scraped rows to a user-supplied URL.

config:
    url:     webhook endpoint (required)
    secret:  optional HMAC-SHA256 key; when set, the body is signed and sent in
             the ``X-Signature`` header as ``sha256=<hexdigest>``
    headers: optional dict of extra request headers
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Dict, List

from .base import BaseDestination, DeliveryResult


class WebhookDestination(BaseDestination):
    def validate(self) -> None:
        if not self.config.get('url'):
            raise ValueError("webhook destination requires 'url'")

    def deliver(self, columns: List[str], rows: List[Dict[str, Any]]) -> DeliveryResult:
        self.validate()
        import requests

        payload = {'columns': columns, 'count': len(rows), 'rows': rows}
        body = json.dumps(payload, ensure_ascii=False, default=str).encode('utf-8')

        headers = {'Content-Type': 'application/json'}
        headers.update(self.config.get('headers') or {})
        secret = self.config.get('secret')
        if secret:
            sig = hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
            headers['X-Signature'] = f"sha256={sig}"

        try:
            resp = requests.post(self.config['url'], data=body, headers=headers, timeout=30)
            resp.raise_for_status()
            return DeliveryResult(success=True, rows_delivered=len(rows),
                                  detail={'status_code': resp.status_code})
        except Exception as e:  # noqa: BLE001
            return DeliveryResult(success=False, error=str(e))
