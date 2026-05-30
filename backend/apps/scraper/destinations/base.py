"""Destination interface + factory."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class DeliveryResult:
    success: bool
    rows_delivered: int = 0
    error: str = ""
    detail: Dict[str, Any] = None


class BaseDestination(ABC):
    """A place to push scraped rows after a run."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}

    @abstractmethod
    def deliver(self, columns: List[str], rows: List[Dict[str, Any]]) -> DeliveryResult:
        raise NotImplementedError

    def validate(self) -> None:
        """Raise ValueError if the config is missing required keys."""
        return None


def get_destination(dest_type: str, config: Dict[str, Any]) -> BaseDestination:
    if dest_type == 'postgres':
        from .postgres import PostgresDestination
        return PostgresDestination(config)
    if dest_type == 'google_sheets':
        from .sheets import GoogleSheetsDestination
        return GoogleSheetsDestination(config)
    if dest_type == 'webhook':
        from .webhook import WebhookDestination
        return WebhookDestination(config)
    raise ValueError(f"Unknown destination type: {dest_type}")
