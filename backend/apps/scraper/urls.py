"""
Scraper URLs.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ScrapeJobViewSet,
    JobRunViewSet,
    ScrapedItemViewSet,
    TestSelectorsView,
    AISchemaGenerationView,
    TaskStatusView,
    SnapshotView,
    InferSelectorsView,
    DataDestinationViewSet,
    DiscoverSectionsView,
    DiscoverItemsView,
    ScrapeRecipeViewSet,
    PreviewScrapeView,
)

app_name = 'scraper'

router = DefaultRouter()
router.register(r'jobs', ScrapeJobViewSet, basename='job')
router.register(r'runs', JobRunViewSet, basename='run')
router.register(r'items', ScrapedItemViewSet, basename='item')
router.register(r'destinations', DataDestinationViewSet, basename='destination')
router.register(r'recipes', ScrapeRecipeViewSet, basename='recipe')

urlpatterns = [
    # Router URLs
    path('', include(router.urls)),

    # Custom endpoints
    path('test-selectors/', TestSelectorsView.as_view(), name='test-selectors'),
    path('ai-generate-schema/', AISchemaGenerationView.as_view(), name='ai-generate-schema'),
    path('snapshot/', SnapshotView.as_view(), name='snapshot'),
    path('infer-selectors/', InferSelectorsView.as_view(), name='infer-selectors'),
    path('discover-sections/', DiscoverSectionsView.as_view(), name='discover-sections'),
    path('discover-items/', DiscoverItemsView.as_view(), name='discover-items'),
    path('preview/', PreviewScrapeView.as_view(), name='preview'),
    path('task-status/<str:task_id>/', TaskStatusView.as_view(), name='task-status'),
]
