"""
Core utilities and helper functions.
"""
import hashlib
import json
from typing import Dict, Any, Optional
from urllib.parse import urlparse
import logging

logger = logging.getLogger(__name__)


def generate_unique_hash(data: Dict[str, Any]) -> str:
    """
    Generate a unique hash for data deduplication.

    Args:
        data: Dictionary containing the data to hash

    Returns:
        SHA256 hash string
    """
    # Sort keys to ensure consistent hashing
    sorted_data = json.dumps(data, sort_keys=True)
    return hashlib.sha256(sorted_data.encode()).hexdigest()


def validate_url(url: str) -> bool:
    """
    Validate if a URL is properly formatted.

    Args:
        url: URL string to validate

    Returns:
        True if valid, False otherwise
    """
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


def extract_domain(url: str) -> Optional[str]:
    """
    Extract domain from URL.

    Args:
        url: URL string

    Returns:
        Domain string or None if invalid
    """
    try:
        parsed = urlparse(url)
        return parsed.netloc
    except Exception:
        return None


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename by removing invalid characters.

    Args:
        filename: Original filename

    Returns:
        Sanitized filename
    """
    import re
    # Remove invalid characters
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Limit length
    return filename[:255]


def format_bytes(bytes_value: int) -> str:
    """
    Format bytes into human-readable format.

    Args:
        bytes_value: Number of bytes

    Returns:
        Formatted string (e.g., "1.5 MB")
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_value < 1024.0:
            return f"{bytes_value:.2f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.2f} PB"


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """
    Truncate text to maximum length.

    Args:
        text: Text to truncate
        max_length: Maximum length
        suffix: Suffix to add if truncated

    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


class RateLimiter:
    """
    Simple rate limiter for controlling request rates.
    """
    def __init__(self, rate: int = 1):
        """
        Initialize rate limiter.

        Args:
            rate: Maximum requests per second
        """
        self.rate = rate
        self.last_request = {}

    def can_make_request(self, domain: str) -> bool:
        """
        Check if a request can be made for a domain.

        Args:
            domain: Domain to check

        Returns:
            True if request can be made, False otherwise
        """
        import time
        now = time.time()

        if domain not in self.last_request:
            self.last_request[domain] = now
            return True

        time_since_last = now - self.last_request[domain]
        min_interval = 1.0 / self.rate

        if time_since_last >= min_interval:
            self.last_request[domain] = now
            return True

        return False

    def wait_if_needed(self, domain: str):
        """
        Wait if rate limit would be exceeded.

        Args:
            domain: Domain to check
        """
        import time
        while not self.can_make_request(domain):
            time.sleep(0.1)
