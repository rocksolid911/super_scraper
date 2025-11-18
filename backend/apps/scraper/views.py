"""
Scraper API views.
"""
import csv
import json
import logging
from datetime import datetime
from django.http import HttpResponse, StreamingHttpResponse
from django.db.models import Q, Count
from django.utils import timezone
from rest_framework import viewsets, status, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters

from .models import ScrapeJob, JobRun, ScrapedItem, WebsiteDomain
from .serializers import (
    ScrapeJobSerializer,
    ScrapeJobListSerializer,
    CreateScrapeJobSerializer,
    JobRunSerializer,
    JobRunListSerializer,
    ScrapedItemSerializer,
    UpdateScheduleSerializer,
    AISchemaGenerationSerializer,
    ExportDataSerializer,
    WebsiteDomainSerializer
)
from .tasks import (
    execute_scrape_job,
    test_selectors_task,
    generate_ai_schema_task,
    cancel_job_run
)

logger = logging.getLogger(__name__)


class LargeResultSetPagination(PageNumberPagination):
    """Pagination for large result sets."""
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 1000


class ScrapeJobViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing scrape jobs.
    """
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'mode', 'is_scheduled']
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'updated_at', 'last_run_at', 'name']
    ordering = ['-created_at']

    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return ScrapeJobListSerializer
        elif self.action == 'create':
            return CreateScrapeJobSerializer
        return ScrapeJobSerializer

    def get_queryset(self):
        """Return jobs for current user only."""
        return ScrapeJob.objects.filter(
            user=self.request.user
        ).select_related('user').prefetch_related('runs')

    @action(detail=True, methods=['post'])
    def run(self, request, pk=None):
        """
        Trigger immediate execution of a job.
        """
        job = self.get_object()

        # Validate job configuration
        if not job.configuration.get('urls'):
            return Response(
                {'error': 'Job has no URLs configured'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not job.configuration.get('selectors'):
            return Response(
                {'error': 'Job has no selectors configured'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Execute job
        task = execute_scrape_job.delay(job.id)

        # Create pending job run
        job_run = JobRun.objects.create(
            job=job,
            status=JobRun.Status.PENDING,
            task_id=task.id
        )

        return Response({
            'message': 'Job execution started',
            'run_id': job_run.id,
            'task_id': task.id
        }, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        """Pause a scheduled job."""
        job = self.get_object()
        job.status = ScrapeJob.Status.PAUSED
        job.save(update_fields=['status', 'updated_at'])

        return Response({
            'message': 'Job paused successfully',
            'status': job.status
        })

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Activate a paused job."""
        job = self.get_object()
        job.status = ScrapeJob.Status.ACTIVE
        job.save(update_fields=['status', 'updated_at'])

        return Response({
            'message': 'Job activated successfully',
            'status': job.status
        })

    @action(detail=True, methods=['put', 'patch'])
    def schedule(self, request, pk=None):
        """Update job schedule."""
        job = self.get_object()
        serializer = UpdateScheduleSerializer(data=request.data)

        if serializer.is_valid():
            job.is_scheduled = serializer.validated_data['is_scheduled']
            job.schedule_config = serializer.validated_data.get('schedule_config', {})

            if job.is_scheduled:
                # Calculate next run time
                from .tasks import calculate_next_run_time
                job.next_run_at = calculate_next_run_time(job.schedule_config)

            job.save()

            return Response(ScrapeJobSerializer(job).data)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    def runs(self, request, pk=None):
        """Get all runs for a job."""
        job = self.get_object()
        runs = job.runs.all().order_by('-created_at')

        # Pagination
        page = self.paginate_queryset(runs)
        if page is not None:
            serializer = JobRunListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = JobRunListSerializer(runs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def items(self, request, pk=None):
        """Get all scraped items for a job."""
        job = self.get_object()
        items = job.items.all().order_by('-created_at')

        # Optional filters
        run_id = request.query_params.get('run_id')
        if run_id:
            items = items.filter(run_id=run_id)

        date_from = request.query_params.get('date_from')
        if date_from:
            items = items.filter(created_at__gte=date_from)

        date_to = request.query_params.get('date_to')
        if date_to:
            items = items.filter(created_at__lte=date_to)

        # Pagination
        page = self.paginate_queryset(items)
        if page is not None:
            serializer = ScrapedItemSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = ScrapedItemSerializer(items, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def export(self, request, pk=None):
        """Export job data."""
        job = self.get_object()
        serializer = ExportDataSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        export_format = serializer.validated_data['format']
        run_id = serializer.validated_data.get('run_id')
        date_from = serializer.validated_data.get('date_from')
        date_to = serializer.validated_data.get('date_to')

        # Get items
        items = job.items.all()

        if run_id:
            items = items.filter(run_id=run_id)
        if date_from:
            items = items.filter(created_at__gte=date_from)
        if date_to:
            items = items.filter(created_at__lte=date_to)

        items = items.order_by('-created_at')

        # Export
        if export_format == 'csv':
            return self._export_csv(job, items)
        elif export_format == 'json':
            return self._export_json(job, items)
        elif export_format == 'xlsx':
            return self._export_xlsx(job, items)

        return Response(
            {'error': 'Unsupported format'},
            status=status.HTTP_400_BAD_REQUEST
        )

    def _export_csv(self, job, items):
        """Export items as CSV."""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = (
            f'attachment; filename="{job.name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        )

        if not items.exists():
            return response

        # Get all field names from items
        field_names = set()
        for item in items[:100]:  # Sample first 100 items for fields
            field_names.update(item.data.keys())

        field_names = sorted(field_names)

        writer = csv.DictWriter(response, fieldnames=['id', 'created_at', 'source_url'] + field_names)
        writer.writeheader()

        for item in items:
            row = {
                'id': item.id,
                'created_at': item.created_at.isoformat(),
                'source_url': item.source_url
            }
            row.update(item.data)
            writer.writerow(row)

        return response

    def _export_json(self, job, items):
        """Export items as JSON."""
        response = HttpResponse(content_type='application/json')
        response['Content-Disposition'] = (
            f'attachment; filename="{job.name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json"'
        )

        data = {
            'job': {
                'id': job.id,
                'name': job.name,
                'description': job.description
            },
            'exported_at': timezone.now().isoformat(),
            'total_items': items.count(),
            'items': [
                {
                    'id': item.id,
                    'created_at': item.created_at.isoformat(),
                    'source_url': item.source_url,
                    'data': item.data
                }
                for item in items
            ]
        }

        response.write(json.dumps(data, indent=2))
        return response

    def _export_xlsx(self, job, items):
        """Export items as Excel."""
        try:
            import pandas as pd
            from io import BytesIO
        except ImportError:
            return Response(
                {'error': 'Excel export requires pandas and openpyxl'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        if not items.exists():
            return HttpResponse(status=status.HTTP_204_NO_CONTENT)

        # Convert to DataFrame
        data = []
        for item in items:
            row = {
                'ID': item.id,
                'Created At': item.created_at,
                'Source URL': item.source_url
            }
            row.update(item.data)
            data.append(row)

        df = pd.DataFrame(data)

        # Create Excel file
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Data')

        output.seek(0)

        response = HttpResponse(
            output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = (
            f'attachment; filename="{job.name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'
        )

        return response

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """Get overall statistics for user's jobs."""
        jobs = self.get_queryset()

        stats = {
            'total_jobs': jobs.count(),
            'active_jobs': jobs.filter(status=ScrapeJob.Status.ACTIVE).count(),
            'scheduled_jobs': jobs.filter(is_scheduled=True).count(),
            'total_runs': sum(job.total_runs for job in jobs),
            'successful_runs': sum(job.successful_runs for job in jobs),
            'failed_runs': sum(job.failed_runs for job in jobs),
            'total_items_scraped': sum(job.total_items_scraped for job in jobs),
        }

        return Response(stats)


class JobRunViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing job runs.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = JobRunSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['status', 'job']
    ordering_fields = ['created_at', 'started_at', 'finished_at']
    ordering = ['-created_at']

    def get_queryset(self):
        """Return runs for current user's jobs only."""
        return JobRun.objects.filter(
            job__user=self.request.user
        ).select_related('job')

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel a running job."""
        job_run = self.get_object()

        if not job_run.is_running:
            return Response(
                {'error': 'Job run is not in a running state'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Cancel via Celery
        result = cancel_job_run.delay(job_run.id)

        return Response({
            'message': 'Job cancellation initiated',
            'run_id': job_run.id
        })

    @action(detail=True, methods=['get'])
    def items(self, request, pk=None):
        """Get all items for this run."""
        job_run = self.get_object()
        items = job_run.items.all().order_by('-created_at')

        page = self.paginate_queryset(items)
        if page is not None:
            serializer = ScrapedItemSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = ScrapedItemSerializer(items, many=True)
        return Response(serializer.data)


class ScrapedItemViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing scraped items.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ScrapedItemSerializer
    pagination_class = LargeResultSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['job', 'run']
    search_fields = ['data', 'source_url']
    ordering_fields = ['created_at']
    ordering = ['-created_at']

    def get_queryset(self):
        """Return items for current user's jobs only."""
        return ScrapedItem.objects.filter(
            job__user=self.request.user
        ).select_related('job', 'run')


class TestSelectorsView(generics.GenericAPIView):
    """
    Test selectors on a URL.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Test selectors."""
        url = request.data.get('url')
        selectors = request.data.get('selectors')
        use_js_rendering = request.data.get('use_js_rendering', False)

        if not url or not selectors:
            return Response(
                {'error': 'URL and selectors are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Test asynchronously
        task = test_selectors_task.delay(url, selectors, use_js_rendering)

        return Response({
            'message': 'Selector testing started',
            'task_id': task.id
        }, status=status.HTTP_202_ACCEPTED)


class AISchemaGenerationView(generics.GenericAPIView):
    """
    Generate schema using AI.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = AISchemaGenerationSerializer

    def post(self, request):
        """Generate schema from prompt."""
        serializer = self.get_serializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        urls = serializer.validated_data['urls']
        scrape_prompt = serializer.validated_data['scrape_prompt']
        use_js_rendering = serializer.validated_data['use_js_rendering']

        # Generate schema asynchronously
        task = generate_ai_schema_task.delay(urls, scrape_prompt, use_js_rendering)

        return Response({
            'message': 'AI schema generation started',
            'task_id': task.id
        }, status=status.HTTP_202_ACCEPTED)


class TaskStatusView(generics.GenericAPIView):
    """
    Check Celery task status.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, task_id):
        """Get task status."""
        from celery.result import AsyncResult

        task = AsyncResult(task_id)

        response = {
            'task_id': task_id,
            'status': task.status,
            'ready': task.ready(),
            'successful': task.successful() if task.ready() else None
        }

        if task.ready():
            if task.successful():
                response['result'] = task.result
            else:
                response['error'] = str(task.info)

        return Response(response)
