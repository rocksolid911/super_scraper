"""
Authentication app configuration.
"""
from django.apps import AppConfig


class AuthenticationConfig(AppConfig):
    """Authentication app configuration."""
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.authentication'
    verbose_name = 'Authentication'
