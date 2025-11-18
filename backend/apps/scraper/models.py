"""
Scraper models - ScrapeJob, JobRun, ScrapedItem.
"""
from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import URLValidator
from apps.core.models import TimeStampedModel, SoftDeleteModel
import json

User = get_user_model()


class ScrapeJob(SoftDeleteModel):
    """
    Model for scraping job configuration.
    """
    class Mode(models.TextChoices):
        VISUAL = 'visual', 'Visual Selector'
        PROMPT = 'prompt', 'AI Prompt-based'

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        PAUSED = 'paused', 'Paused'
        DRAFT = 'draft', 'Draft'

    # Basic info
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='scrape_jobs'
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    mode = models.CharField(
        max_length=20,
        choices=Mode.choices,
        default=Mode.VISUAL
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT
    )

    # Configuration
    configuration = models.JSONField(
        default=dict,
        help_text='Job configuration including URLs, selectors, pagination, etc.'
    )

    # Schedule configuration
    is_scheduled = models.BooleanField(default=False)
    schedule_config = models.JSONField(
        default=dict,
        blank=True,
        help_text='Schedule configuration (interval, cron, etc.)'
    )
    next_run_at = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)

    # Stats
    total_runs = models.IntegerField(default=0)
    successful_runs = models.IntegerField(default=0)
    failed_runs = models.IntegerField(default=0)
    total_items_scraped = models.IntegerField(default=0)

    # Settings
    respect_robots_txt = models.BooleanField(default=True)
    use_js_rendering = models.BooleanField(default=False)
    max_pages = models.IntegerField(default=100)
    max_depth = models.IntegerField(default=3)
    rate_limit = models.FloatField(
        default=1.0,
        help_text='Requests per second'
    )

    class Meta:
        db_table = 'scrape_jobs'
        verbose_name = 'Scrape Job'
        verbose_name_plural = 'Scrape Jobs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['is_scheduled', 'next_run_at']),
        ]

    def __str__(self):
        return f"{self.name} ({self.user.email})"

    @property
    def success_rate(self):
        """Calculate success rate percentage."""
        if self.total_runs == 0:
            return 0
        return round((self.successful_runs / self.total_runs) * 100, 2)

    @property
    def urls(self):
        """Extract URLs from configuration."""
        return self.configuration.get('urls', [])

    @property
    def selectors(self):
        """Extract selectors from configuration."""
        return self.configuration.get('selectors', {})

    @property
    def schema(self):
        """Extract schema from configuration."""
        return self.configuration.get('schema', {})


class JobRun(TimeStampedModel):
    """
    Model for individual job run execution.
    """
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        RUNNING = 'running', 'Running'
        SUCCESS = 'success', 'Success'
        PARTIAL = 'partial', 'Partial Success'
        FAILED = 'failed', 'Failed'
        CANCELLED = 'cancelled', 'Cancelled'

    job = models.ForeignKey(
        ScrapeJob,
        on_delete=models.CASCADE,
        related_name='runs'
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )

    # Execution tracking
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)

    # Results
    items_scraped = models.IntegerField(default=0)
    pages_visited = models.IntegerField(default=0)
    errors_count = models.IntegerField(default=0)

    # Error information
    error_message = models.TextField(blank=True)
    error_traceback = models.TextField(blank=True)

    # Stats and metadata
    stats = models.JSONField(
        default=dict,
        blank=True,
        help_text='Detailed statistics about the run'
    )

    # Celery task ID for tracking
    task_id = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = 'job_runs'
        verbose_name = 'Job Run'
        verbose_name_plural = 'Job Runs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['job', 'status']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['task_id']),
        ]

    def __str__(self):
        return f"Run {self.id} - {self.job.name} ({self.status})"

    @property
    def is_completed(self):
        """Check if run is completed."""
        return self.status in [
            self.Status.SUCCESS,
            self.Status.PARTIAL,
            self.Status.FAILED,
            self.Status.CANCELLED
        ]

    @property
    def is_running(self):
        """Check if run is currently running."""
        return self.status in [self.Status.PENDING, self.Status.RUNNING]


class ScrapedItem(TimeStampedModel):
    """
    Model for individual scraped data items.
    """
    job = models.ForeignKey(
        ScrapeJob,
        on_delete=models.CASCADE,
        related_name='items'
    )
    run = models.ForeignKey(
        JobRun,
        on_delete=models.CASCADE,
        related_name='items'
    )

    # Data
    data = models.JSONField(
        help_text='Scraped data as JSON'
    )

    # Source information
    source_url = models.URLField(max_length=2048)

    # Deduplication
    unique_hash = models.CharField(
        max_length=64,
        db_index=True,
        help_text='SHA256 hash for deduplication'
    )

    # Additional metadata
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text='Additional metadata about the scraped item'
    )

    class Meta:
        db_table = 'scraped_items'
        verbose_name = 'Scraped Item'
        verbose_name_plural = 'Scraped Items'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['job', 'created_at']),
            models.Index(fields=['run', 'created_at']),
            models.Index(fields=['unique_hash']),
            models.Index(fields=['job', 'unique_hash']),
        ]
        unique_together = [['job', 'unique_hash']]

    def __str__(self):
        return f"Item {self.id} from {self.job.name}"

    @property
    def data_preview(self):
        """Get a preview of the data."""
        data_str = json.dumps(self.data, indent=2)
        if len(data_str) > 200:
            return data_str[:200] + '...'
        return data_str


class WebsiteDomain(TimeStampedModel):
    """
    Model for tracking website domain settings and statistics.
    """
    domain = models.CharField(max_length=255, unique=True, db_index=True)

    # Robots.txt
    robots_txt_content = models.TextField(blank=True)
    robots_txt_last_fetched = models.DateTimeField(null=True, blank=True)
    robots_txt_url = models.URLField(blank=True)

    # Rate limiting
    rate_limit = models.FloatField(
        default=1.0,
        help_text='Requests per second for this domain'
    )

    # Statistics
    total_requests = models.IntegerField(default=0)
    failed_requests = models.IntegerField(default=0)
    last_request_at = models.DateTimeField(null=True, blank=True)

    # Settings
    is_blocked = models.BooleanField(
        default=False,
        help_text='Whether scraping is blocked for this domain'
    )
    block_reason = models.TextField(blank=True)

    class Meta:
        db_table = 'website_domains'
        verbose_name = 'Website Domain'
        verbose_name_plural = 'Website Domains'
        ordering = ['domain']

    def __str__(self):
        return self.domain
