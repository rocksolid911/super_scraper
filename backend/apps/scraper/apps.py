"""
Scraper app configuration.
"""
from django.apps import AppConfig


class ScraperConfig(AppConfig):
    """Scraper app configuration."""
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.scraper'
    verbose_name = 'Web Scraper'

    def ready(self):
        """Import signals when app is ready."""
        import apps.scraper.signals  # noqa
