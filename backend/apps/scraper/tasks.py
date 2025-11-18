"""
Celery tasks for web scraping.
"""
import asyncio
import logging
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from celery import shared_task
from .models import ScrapeJob, JobRun, ScrapedItem, WebsiteDomain
from .scraping_engine import ScrapingEngine
from apps.core.utils import generate_unique_hash

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def execute_scrape_job(self, job_id: int) -> dict:
    """
    Execute a scraping job.

    Args:
        job_id: ID of the ScrapeJob to execute

    Returns:
        Dictionary with execution results
    """
    try:
        job = ScrapeJob.objects.get(id=job_id)
    except ScrapeJob.DoesNotExist:
        logger.error(f"ScrapeJob {job_id} does not exist")
        return {'success': False, 'error': 'Job not found'}

    # Create job run
    job_run = JobRun.objects.create(
        job=job,
        status=JobRun.Status.RUNNING,
        started_at=timezone.now(),
        task_id=self.request.id
    )

    try:
        logger.info(f"Starting scrape job: {job.name} (ID: {job_id})")

        # Get configuration
        config = job.configuration
        urls = config.get('urls', [])
        selectors = config.get('selectors', {})
        pagination_config = config.get('pagination')

        if not urls:
            raise ValueError("No URLs configured for this job")

        if not selectors:
            raise ValueError("No selectors configured for this job")

        # Initialize scraping engine
        engine = ScrapingEngine(
            use_js_rendering=job.use_js_rendering,
            respect_robots_txt=job.respect_robots_txt,
            rate_limit=job.rate_limit,
            timeout=settings.SCRAPER_CONFIG['DEFAULT_TIMEOUT'],
            max_retries=settings.SCRAPER_CONFIG['MAX_RETRIES']
        )

        # Scrape all URLs
        all_items = []
        total_pages = 0
        urls_visited = []

        for url in urls:
            logger.info(f"Scraping URL: {url}")

            # Run async scraping
            result = asyncio.run(
                engine.scrape_url(
                    url=url,
                    selectors=selectors,
                    pagination_config=pagination_config,
                    max_pages=job.max_pages
                )
            )

            items = result['items']
            all_items.extend(items)
            total_pages += result['pages_visited']
            urls_visited.extend(result['urls_visited'])

            logger.info(f"Scraped {len(items)} items from {url}")

        # Save scraped items
        items_created = 0
        items_duplicated = 0

        for item_data in all_items:
            # Generate unique hash for deduplication
            unique_hash = generate_unique_hash(item_data)

            # Check if item already exists
            if ScrapedItem.objects.filter(
                job=job,
                unique_hash=unique_hash
            ).exists():
                items_duplicated += 1
                continue

            # Create scraped item
            ScrapedItem.objects.create(
                job=job,
                run=job_run,
                data=item_data,
                source_url=item_data.get('_source_url', urls[0]),
                unique_hash=unique_hash,
                metadata={
                    'scraped_at': timezone.now().isoformat(),
                    'engine': 'playwright' if job.use_js_rendering else 'requests'
                }
            )
            items_created += 1

        # Calculate duration
        finished_at = timezone.now()
        duration = (finished_at - job_run.started_at).total_seconds()

        # Update job run
        job_run.status = JobRun.Status.SUCCESS
        job_run.finished_at = finished_at
        job_run.duration_seconds = duration
        job_run.items_scraped = items_created
        job_run.pages_visited = total_pages
        job_run.stats = {
            'total_items_found': len(all_items),
            'items_created': items_created,
            'items_duplicated': items_duplicated,
            'urls_visited': urls_visited,
            'urls_count': len(urls_visited)
        }
        job_run.save()

        # Update job statistics
        job.total_runs += 1
        job.successful_runs += 1
        job.total_items_scraped += items_created
        job.last_run_at = finished_at

        # Update next run time if scheduled
        if job.is_scheduled:
            job.next_run_at = calculate_next_run_time(job.schedule_config)

        job.save()

        logger.info(
            f"Job {job.name} completed successfully. "
            f"Scraped {items_created} items in {duration:.2f}s"
        )

        return {
            'success': True,
            'job_id': job_id,
            'run_id': job_run.id,
            'items_scraped': items_created,
            'pages_visited': total_pages,
            'duration': duration
        }

    except Exception as e:
        logger.error(f"Job {job_id} failed: {str(e)}", exc_info=True)

        # Update job run as failed
        job_run.status = JobRun.Status.FAILED
        job_run.finished_at = timezone.now()
        job_run.error_message = str(e)
        job_run.duration_seconds = (
            job_run.finished_at - job_run.started_at
        ).total_seconds()
        job_run.save()

        # Update job statistics
        job.total_runs += 1
        job.failed_runs += 1
        job.last_run_at = timezone.now()
        job.save()

        # Retry if not max retries
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))

        return {
            'success': False,
            'job_id': job_id,
            'run_id': job_run.id,
            'error': str(e)
        }


@shared_task
def check_scheduled_jobs():
    """
    Check for scheduled jobs that need to run.
    """
    logger.info("Checking for scheduled jobs...")

    now = timezone.now()

    # Find jobs that are due to run
    jobs = ScrapeJob.objects.filter(
        is_scheduled=True,
        status=ScrapeJob.Status.ACTIVE,
        next_run_at__lte=now,
        deleted_at__isnull=True
    )

    for job in jobs:
        logger.info(f"Scheduling job: {job.name} (ID: {job.id})")

        # Execute job asynchronously
        execute_scrape_job.delay(job.id)

        # Update next run time
        job.next_run_at = calculate_next_run_time(job.schedule_config)
        job.save(update_fields=['next_run_at'])

    logger.info(f"Scheduled {jobs.count()} jobs for execution")

    return {'jobs_scheduled': jobs.count()}


@shared_task
def cleanup_old_job_runs(days: int = 30):
    """
    Clean up old job runs.

    Args:
        days: Delete runs older than this many days
    """
    logger.info(f"Cleaning up job runs older than {days} days...")

    cutoff_date = timezone.now() - timedelta(days=days)

    # Delete old completed runs
    deleted_count, _ = JobRun.objects.filter(
        status__in=[
            JobRun.Status.SUCCESS,
            JobRun.Status.FAILED,
            JobRun.Status.CANCELLED
        ],
        created_at__lt=cutoff_date
    ).delete()

    logger.info(f"Deleted {deleted_count} old job runs")

    return {'deleted_count': deleted_count}


@shared_task
def test_selectors_task(url: str, selectors: dict, use_js_rendering: bool = False) -> dict:
    """
    Test selectors on a URL.

    Args:
        url: URL to test
        selectors: Selectors to test
        use_js_rendering: Whether to use browser

    Returns:
        Test results
    """
    from .scraping_engine import SelectorTester

    try:
        result = asyncio.run(
            SelectorTester.test_selectors(url, selectors, use_js_rendering)
        )
        return result
    except Exception as e:
        logger.error(f"Selector testing failed: {e}")
        return {
            'success': False,
            'error': str(e),
            'items': []
        }


@shared_task
def generate_ai_schema_task(
    urls: list,
    scrape_prompt: str,
    use_js_rendering: bool = False
) -> dict:
    """
    Generate schema using AI.

    Args:
        urls: URLs to analyze
        scrape_prompt: User's scraping request
        use_js_rendering: Whether to use browser

    Returns:
        Generated schema
    """
    from .ai_schema_generator import AISchemaGenerator
    from .scraping_engine import ScrapingEngine

    try:
        # Fetch HTML samples
        engine = ScrapingEngine(
            use_js_rendering=use_js_rendering,
            respect_robots_txt=False
        )

        html_samples = []
        for url in urls[:3]:  # Limit to 3 URLs for analysis
            html = asyncio.run(engine.fetch_page(url))
            if html:
                html_samples.append(html)

        if not html_samples:
            return {
                'success': False,
                'error': 'Failed to fetch any URLs',
                'schema': {}
            }

        # Generate schema with AI
        generator = AISchemaGenerator()
        result = asyncio.run(
            generator.generate_schema(html_samples, scrape_prompt)
        )

        return result

    except Exception as e:
        logger.error(f"AI schema generation failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'schema': {}
        }
    finally:
        asyncio.run(engine.close_browser())


def calculate_next_run_time(schedule_config: dict):
    """
    Calculate next run time based on schedule configuration.

    Args:
        schedule_config: Schedule configuration

    Returns:
        Next run datetime
    """
    from croniter import croniter

    now = timezone.now()
    schedule_type = schedule_config.get('type')

    if schedule_type == 'interval':
        interval_value = schedule_config.get('interval_value', 1)
        interval_unit = schedule_config.get('interval_unit', 'hours')

        if interval_unit == 'minutes':
            delta = timedelta(minutes=interval_value)
        elif interval_unit == 'hours':
            delta = timedelta(hours=interval_value)
        elif interval_unit == 'days':
            delta = timedelta(days=interval_value)
        elif interval_unit == 'weeks':
            delta = timedelta(weeks=interval_value)
        else:
            delta = timedelta(hours=1)

        return now + delta

    elif schedule_type == 'cron':
        cron_expression = schedule_config.get('cron_expression')
        if cron_expression:
            try:
                cron = croniter(cron_expression, now)
                return cron.get_next(timezone.datetime)
            except Exception as e:
                logger.error(f"Invalid cron expression: {e}")
                return now + timedelta(hours=1)

    elif schedule_type == 'once':
        # For one-time jobs, don't schedule next run
        return None

    # Default: 1 hour
    return now + timedelta(hours=1)


@shared_task
def cancel_job_run(run_id: int) -> dict:
    """
    Cancel a running job.

    Args:
        run_id: JobRun ID

    Returns:
        Result dictionary
    """
    try:
        job_run = JobRun.objects.get(id=run_id)

        if not job_run.is_running:
            return {
                'success': False,
                'error': 'Job run is not in a running state'
            }

        # Revoke celery task
        if job_run.task_id:
            from celery import current_app
            current_app.control.revoke(job_run.task_id, terminate=True)

        # Update status
        job_run.status = JobRun.Status.CANCELLED
        job_run.finished_at = timezone.now()
        job_run.duration_seconds = (
            job_run.finished_at - job_run.started_at
        ).total_seconds()
        job_run.save()

        logger.info(f"Cancelled job run {run_id}")

        return {
            'success': True,
            'run_id': run_id
        }

    except JobRun.DoesNotExist:
        return {
            'success': False,
            'error': 'Job run not found'
        }
    except Exception as e:
        logger.error(f"Failed to cancel job run {run_id}: {e}")
        return {
            'success': False,
            'error': str(e)
        }
