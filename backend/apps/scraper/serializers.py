"""
Scraper serializers.
"""
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import ScrapeJob, JobRun, ScrapedItem, WebsiteDomain

User = get_user_model()


class ScrapedItemSerializer(serializers.ModelSerializer):
    """Serializer for scraped items."""
    data_preview = serializers.ReadOnlyField()

    class Meta:
        model = ScrapedItem
        fields = [
            'id', 'job', 'run', 'data', 'data_preview',
            'source_url', 'unique_hash', 'metadata', 'created_at'
        ]
        read_only_fields = ['id', 'unique_hash', 'created_at']


class JobRunSerializer(serializers.ModelSerializer):
    """Serializer for job runs."""
    is_completed = serializers.ReadOnlyField()
    is_running = serializers.ReadOnlyField()
    items_preview = ScrapedItemSerializer(
        source='items',
        many=True,
        read_only=True
    )

    class Meta:
        model = JobRun
        fields = [
            'id', 'job', 'status', 'started_at', 'finished_at',
            'duration_seconds', 'items_scraped', 'pages_visited',
            'errors_count', 'error_message', 'stats', 'task_id',
            'is_completed', 'is_running', 'created_at', 'items_preview'
        ]
        read_only_fields = [
            'id', 'started_at', 'finished_at', 'duration_seconds',
            'items_scraped', 'pages_visited', 'errors_count',
            'error_message', 'stats', 'task_id', 'created_at'
        ]


class JobRunListSerializer(serializers.ModelSerializer):
    """Serializer for job runs list (without items)."""
    is_completed = serializers.ReadOnlyField()
    is_running = serializers.ReadOnlyField()

    class Meta:
        model = JobRun
        fields = [
            'id', 'job', 'status', 'started_at', 'finished_at',
            'duration_seconds', 'items_scraped', 'pages_visited',
            'errors_count', 'is_completed', 'is_running', 'created_at'
        ]
        read_only_fields = fields


class ScrapeJobSerializer(serializers.ModelSerializer):
    """Serializer for scrape jobs."""
    success_rate = serializers.ReadOnlyField()
    urls = serializers.ReadOnlyField()
    selectors = serializers.ReadOnlyField()
    schema = serializers.ReadOnlyField()
    user_email = serializers.EmailField(source='user.email', read_only=True)
    recent_runs = JobRunListSerializer(
        source='runs',
        many=True,
        read_only=True
    )

    class Meta:
        model = ScrapeJob
        fields = [
            'id', 'user', 'user_email', 'name', 'description', 'mode', 'status',
            'configuration', 'is_scheduled', 'schedule_config',
            'next_run_at', 'last_run_at', 'total_runs', 'successful_runs',
            'failed_runs', 'total_items_scraped', 'success_rate',
            'respect_robots_txt', 'use_js_rendering', 'max_pages',
            'max_depth', 'rate_limit', 'urls', 'selectors', 'schema',
            'created_at', 'updated_at', 'recent_runs'
        ]
        read_only_fields = [
            'id', 'user', 'total_runs', 'successful_runs', 'failed_runs',
            'total_items_scraped', 'success_rate', 'created_at', 'updated_at',
            'next_run_at', 'last_run_at'
        ]

    def create(self, validated_data):
        """Create job with user from request."""
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)


class ScrapeJobListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for job listings."""
    success_rate = serializers.ReadOnlyField()
    user_email = serializers.EmailField(source='user.email', read_only=True)

    class Meta:
        model = ScrapeJob
        fields = [
            'id', 'user_email', 'name', 'description', 'mode', 'status',
            'is_scheduled', 'next_run_at', 'last_run_at',
            'total_runs', 'successful_runs', 'failed_runs',
            'total_items_scraped', 'success_rate', 'created_at', 'updated_at'
        ]
        read_only_fields = fields


class CreateScrapeJobSerializer(serializers.ModelSerializer):
    """Serializer for creating a new scrape job."""

    class Meta:
        model = ScrapeJob
        fields = [
            'name', 'description', 'mode', 'configuration',
            'respect_robots_txt', 'use_js_rendering',
            'max_pages', 'max_depth', 'rate_limit'
        ]

    def validate_configuration(self, value):
        """Validate configuration has required fields."""
        if not value.get('urls'):
            raise serializers.ValidationError(
                'Configuration must include at least one URL.'
            )

        urls = value['urls']
        if not isinstance(urls, list) or len(urls) == 0:
            raise serializers.ValidationError(
                'URLs must be a non-empty list.'
            )

        # Validate URLs
        from apps.core.utils import validate_url
        for url in urls:
            if not validate_url(url):
                raise serializers.ValidationError(
                    f'Invalid URL: {url}'
                )

        return value

    def create(self, validated_data):
        """Create job with user from request."""
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)


class UpdateScheduleSerializer(serializers.Serializer):
    """Serializer for updating job schedule."""
    is_scheduled = serializers.BooleanField(required=True)
    schedule_config = serializers.JSONField(required=False)

    def validate(self, attrs):
        """Validate schedule configuration."""
        if attrs.get('is_scheduled') and not attrs.get('schedule_config'):
            raise serializers.ValidationError(
                'schedule_config is required when is_scheduled is True.'
            )

        if attrs.get('schedule_config'):
            config = attrs['schedule_config']
            schedule_type = config.get('type')

            if schedule_type not in ['interval', 'cron', 'once']:
                raise serializers.ValidationError(
                    'schedule_type must be one of: interval, cron, once'
                )

            if schedule_type == 'interval':
                if 'interval_value' not in config or 'interval_unit' not in config:
                    raise serializers.ValidationError(
                        'interval type requires interval_value and interval_unit'
                    )
                if config['interval_unit'] not in ['minutes', 'hours', 'days', 'weeks']:
                    raise serializers.ValidationError(
                        'interval_unit must be one of: minutes, hours, days, weeks'
                    )

            elif schedule_type == 'cron':
                if 'cron_expression' not in config:
                    raise serializers.ValidationError(
                        'cron type requires cron_expression'
                    )

        return attrs


class AISchemaGenerationSerializer(serializers.Serializer):
    """Serializer for AI schema generation request."""
    urls = serializers.ListField(
        child=serializers.URLField(),
        min_length=1,
        max_length=10
    )
    scrape_prompt = serializers.CharField(
        min_length=10,
        max_length=5000
    )
    use_js_rendering = serializers.BooleanField(default=False)


class ExportDataSerializer(serializers.Serializer):
    """Serializer for data export request."""
    format = serializers.ChoiceField(
        choices=['csv', 'json', 'xlsx'],
        default='csv'
    )
    run_id = serializers.IntegerField(required=False)
    date_from = serializers.DateTimeField(required=False)
    date_to = serializers.DateTimeField(required=False)


class WebsiteDomainSerializer(serializers.ModelSerializer):
    """Serializer for website domains."""

    class Meta:
        model = WebsiteDomain
        fields = [
            'id', 'domain', 'robots_txt_content', 'robots_txt_last_fetched',
            'robots_txt_url', 'rate_limit', 'total_requests',
            'failed_requests', 'last_request_at', 'is_blocked',
            'block_reason', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'total_requests', 'failed_requests', 'last_request_at',
            'created_at', 'updated_at'
        ]
