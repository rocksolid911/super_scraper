"""
Scraper admin configuration.
"""
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from .models import ScrapeJob, JobRun, ScrapedItem, WebsiteDomain


@admin.register(ScrapeJob)
class ScrapeJobAdmin(admin.ModelAdmin):
    """Admin configuration for ScrapeJob model."""
    list_display = [
        'name', 'user', 'mode', 'status', 'is_scheduled',
        'total_runs', 'success_rate_display', 'total_items_scraped',
        'last_run_at', 'created_at'
    ]
    list_filter = ['mode', 'status', 'is_scheduled', 'created_at', 'use_js_rendering']
    search_fields = ['name', 'description', 'user__email']
    readonly_fields = [
        'created_at', 'updated_at', 'total_runs', 'successful_runs',
        'failed_runs', 'total_items_scraped', 'last_run_at'
    ]
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'name', 'description', 'mode', 'status')
        }),
        ('Configuration', {
            'fields': (
                'configuration', 'respect_robots_txt', 'use_js_rendering',
                'max_pages', 'max_depth', 'rate_limit'
            )
        }),
        ('Schedule', {
            'fields': ('is_scheduled', 'schedule_config', 'next_run_at', 'last_run_at')
        }),
        ('Statistics', {
            'fields': (
                'total_runs', 'successful_runs', 'failed_runs', 'total_items_scraped'
            )
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'deleted_at')
        }),
    )

    def success_rate_display(self, obj):
        """Display success rate with color."""
        rate = obj.success_rate
        if rate >= 80:
            color = 'green'
        elif rate >= 50:
            color = 'orange'
        else:
            color = 'red'
        return format_html(
            '<span style="color: {};">{:.1f}%</span>',
            color, rate
        )
    success_rate_display.short_description = 'Success Rate'

    actions = ['activate_jobs', 'pause_jobs', 'run_jobs']

    def activate_jobs(self, request, queryset):
        """Activate selected jobs."""
        updated = queryset.update(status=ScrapeJob.Status.ACTIVE)
        self.message_user(request, f'{updated} jobs activated.')
    activate_jobs.short_description = 'Activate selected jobs'

    def pause_jobs(self, request, queryset):
        """Pause selected jobs."""
        updated = queryset.update(status=ScrapeJob.Status.PAUSED)
        self.message_user(request, f'{updated} jobs paused.')
    pause_jobs.short_description = 'Pause selected jobs'

    def run_jobs(self, request, queryset):
        """Run selected jobs immediately."""
        from .tasks import execute_scrape_job
        count = 0
        for job in queryset:
            execute_scrape_job.delay(job.id)
            count += 1
        self.message_user(request, f'{count} jobs scheduled for execution.')
    run_jobs.short_description = 'Run selected jobs now'


@admin.register(JobRun)
class JobRunAdmin(admin.ModelAdmin):
    """Admin configuration for JobRun model."""
    list_display = [
        'id', 'job_link', 'status_display', 'items_scraped',
        'pages_visited', 'errors_count', 'duration_display',
        'started_at', 'finished_at'
    ]
    list_filter = ['status', 'created_at', 'started_at']
    search_fields = ['job__name', 'error_message', 'task_id']
    readonly_fields = [
        'job', 'started_at', 'finished_at', 'duration_seconds',
        'items_scraped', 'pages_visited', 'errors_count',
        'error_message', 'error_traceback', 'stats', 'task_id', 'created_at'
    ]
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Job Information', {
            'fields': ('job', 'status', 'task_id')
        }),
        ('Execution', {
            'fields': (
                'started_at', 'finished_at', 'duration_seconds'
            )
        }),
        ('Results', {
            'fields': (
                'items_scraped', 'pages_visited', 'errors_count', 'stats'
            )
        }),
        ('Errors', {
            'fields': ('error_message', 'error_traceback'),
            'classes': ('collapse',)
        }),
    )

    def job_link(self, obj):
        """Link to job."""
        url = reverse('admin:scraper_scrapejob_change', args=[obj.job.id])
        return format_html('<a href="{}">{}</a>', url, obj.job.name)
    job_link.short_description = 'Job'

    def status_display(self, obj):
        """Display status with color."""
        colors = {
            JobRun.Status.SUCCESS: 'green',
            JobRun.Status.FAILED: 'red',
            JobRun.Status.RUNNING: 'blue',
            JobRun.Status.PENDING: 'orange',
            JobRun.Status.PARTIAL: 'orange',
            JobRun.Status.CANCELLED: 'gray',
        }
        color = colors.get(obj.status, 'black')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, obj.get_status_display()
        )
    status_display.short_description = 'Status'

    def duration_display(self, obj):
        """Display duration in human-readable format."""
        if obj.duration_seconds:
            minutes, seconds = divmod(int(obj.duration_seconds), 60)
            hours, minutes = divmod(minutes, 60)
            if hours > 0:
                return f'{hours}h {minutes}m {seconds}s'
            elif minutes > 0:
                return f'{minutes}m {seconds}s'
            else:
                return f'{seconds}s'
        return '-'
    duration_display.short_description = 'Duration'


@admin.register(ScrapedItem)
class ScrapedItemAdmin(admin.ModelAdmin):
    """Admin configuration for ScrapedItem model."""
    list_display = [
        'id', 'job_link', 'run_link', 'source_url_short',
        'unique_hash_short', 'created_at'
    ]
    list_filter = ['created_at', 'job', 'run']
    search_fields = ['source_url', 'unique_hash', 'data']
    readonly_fields = [
        'job', 'run', 'data', 'source_url', 'unique_hash',
        'metadata', 'created_at'
    ]
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Links', {
            'fields': ('job', 'run', 'source_url')
        }),
        ('Data', {
            'fields': ('data', 'metadata')
        }),
        ('Identification', {
            'fields': ('unique_hash', 'created_at')
        }),
    )

    def job_link(self, obj):
        """Link to job."""
        url = reverse('admin:scraper_scrapejob_change', args=[obj.job.id])
        return format_html('<a href="{}">{}</a>', url, obj.job.name)
    job_link.short_description = 'Job'

    def run_link(self, obj):
        """Link to run."""
        url = reverse('admin:scraper_jobrun_change', args=[obj.run.id])
        return format_html('<a href="{}">Run #{}</a>', url, obj.run.id)
    run_link.short_description = 'Run'

    def source_url_short(self, obj):
        """Display shortened URL."""
        url = obj.source_url
        if len(url) > 50:
            return url[:47] + '...'
        return url
    source_url_short.short_description = 'Source URL'

    def unique_hash_short(self, obj):
        """Display shortened hash."""
        return obj.unique_hash[:16] + '...'
    unique_hash_short.short_description = 'Hash'


@admin.register(WebsiteDomain)
class WebsiteDomainAdmin(admin.ModelAdmin):
    """Admin configuration for WebsiteDomain model."""
    list_display = [
        'domain', 'rate_limit', 'total_requests', 'failed_requests',
        'is_blocked', 'last_request_at', 'robots_txt_last_fetched'
    ]
    list_filter = ['is_blocked', 'created_at']
    search_fields = ['domain', 'block_reason']
    readonly_fields = [
        'total_requests', 'failed_requests', 'last_request_at',
        'created_at', 'updated_at'
    ]

    fieldsets = (
        ('Domain Information', {
            'fields': ('domain', 'rate_limit')
        }),
        ('Robots.txt', {
            'fields': (
                'robots_txt_url', 'robots_txt_content', 'robots_txt_last_fetched'
            )
        }),
        ('Statistics', {
            'fields': (
                'total_requests', 'failed_requests', 'last_request_at'
            )
        }),
        ('Blocking', {
            'fields': ('is_blocked', 'block_reason')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )
