"""
URL Configuration for Universal AI Web Scraper.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework import permissions

urlpatterns = [
    # Admin
    path('admin/', admin.site.admin_view),

    # API endpoints
    path('api/auth/', include('apps.authentication.urls')),
    path('api/scraper/', include('apps.scraper.urls')),
    path('api/', include('apps.core.urls')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Customize admin site
admin.site.site_header = "Universal AI Web Scraper Admin"
admin.site.site_title = "Scraper Admin Portal"
admin.site.index_title = "Welcome to Universal AI Web Scraper"
