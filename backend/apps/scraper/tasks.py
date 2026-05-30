"""
Celery tasks for web scraping.
"""
import asyncio
import logging
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from celery import shared_task
from .models import ScrapeJob, JobRun, ScrapedItem, WebsiteDomain, DataDestination
from .scraping_engine import ScrapingEngine
from apps.core.utils import generate_unique_hash

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def execute_scrape_job(self, job_id: int, run_id: int = None) -> dict:
    """
    Execute a scraping job.

    Args:
        job_id: ID of the ScrapeJob to execute
        run_id: Optional pre-created JobRun to reuse (the API `run` action creates
            one so the caller gets an id immediately). When omitted (e.g. the
            scheduled path) the task creates its own run.

    Returns:
        Dictionary with execution results
    """
    try:
        job = ScrapeJob.objects.get(id=job_id)
    except ScrapeJob.DoesNotExist:
        logger.error(f"ScrapeJob {job_id} does not exist")
        return {'success': False, 'error': 'Job not found'}

    # Reuse the run created by the caller, or create one for scheduled/direct calls.
    job_run = None
    if run_id is not None:
        job_run = JobRun.objects.filter(id=run_id).first()
        if job_run is not None:
            job_run.status = JobRun.Status.RUNNING
            job_run.started_at = timezone.now()
            job_run.task_id = self.request.id
            job_run.save()
    if job_run is None:
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
        scrape_prompt = config.get('prompt') or config.get('scrape_prompt')

        if not urls:
            raise ValueError("No URLs configured for this job")

        # Decide the execution path:
        #   * prompt mode without cached CSS selectors -> agentic LLM extraction
        #   * visual mode / cached selectors           -> deterministic CSS extraction
        has_selectors = bool(selectors and selectors.get('fields'))
        use_agent = (job.mode == ScrapeJob.Mode.PROMPT) and not has_selectors
        agent_errors = []

        if use_agent:
            if not scrape_prompt:
                raise ValueError("Prompt-mode job requires a 'prompt' in its configuration")

            from .agent import run_agent
            logger.info(f"Running LangGraph agent for job {job_id}")
            agent_out = run_agent(
                prompt=scrape_prompt,
                start_urls=urls,
                max_steps=max(job.max_pages, 5),
                max_items=config.get('max_items', 500),
                js=job.use_js_rendering,
                timeout=settings.SCRAPER_CONFIG['DEFAULT_TIMEOUT'],
            )
            all_items = agent_out['rows']
            urls_visited = agent_out['visited']
            total_pages = len(urls_visited)
            agent_errors = agent_out.get('errors', [])
            engine_label = 'langgraph-agent'

            # Cost optimization: if the agent extracted a clean single-page list,
            # derive a CSS schema, verify it reproduces the rows, and cache it so
            # future runs use the cheap deterministic path and skip the LLM entirely.
            try:
                _maybe_cache_css_schema(
                    job, agent_out, urls,
                    job.use_js_rendering, settings.SCRAPER_CONFIG['DEFAULT_TIMEOUT']
                )
            except Exception as e:
                logger.warning(f"CSS schema caching skipped for job {job_id}: {e}")
        else:
            if not has_selectors:
                raise ValueError("No selectors configured for this job")

            # Deterministic CSS extraction (visual mode / cached selectors), one
            # browser lifecycle per run instead of a new event loop per URL.
            engine = ScrapingEngine(
                use_js_rendering=job.use_js_rendering,
                respect_robots_txt=job.respect_robots_txt,
                rate_limit=job.rate_limit,
                timeout=settings.SCRAPER_CONFIG['DEFAULT_TIMEOUT'],
                max_retries=settings.SCRAPER_CONFIG['MAX_RETRIES']
            )

            async def _scrape_all():
                collected = []
                pages = 0
                visited = []
                for url in urls:
                    logger.info(f"Scraping URL: {url}")
                    result = await engine.scrape_url(
                        url=url,
                        selectors=selectors,
                        pagination_config=pagination_config,
                        max_pages=job.max_pages
                    )
                    collected.extend(result['items'])
                    pages += result['pages_visited']
                    visited.extend(result['urls_visited'])
                    logger.info(f"Scraped {len(result['items'])} items from {url}")
                return collected, pages, visited

            all_items, total_pages, urls_visited = asyncio.run(_scrape_all())
            engine_label = 'playwright' if job.use_js_rendering else 'requests'

            # Self-heal: a cached CSS schema that suddenly returns nothing is stale
            # (site changed). Drop it so the next run re-derives via the agent.
            if config.get('css_cached') and len(all_items) == 0:
                logger.warning(f"Cached CSS schema for job {job_id} returned 0 rows; clearing cache")
                job.configuration.pop('selectors', None)
                job.configuration.pop('css_cached', None)
                job.save(update_fields=['configuration', 'updated_at'])

        # Save scraped items
        items_created = 0
        items_duplicated = 0

        for item_data in all_items:
            if not isinstance(item_data, dict):
                continue
            # The agent tags rows with their origin URL; keep it out of the stored data.
            source_url = item_data.pop('_source_url', None) or (urls[0] if urls else '')

            # Skip rows where every value is empty (LLM sometimes returns blank rows).
            if not any(v not in (None, '', []) for v in item_data.values()):
                continue

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
                source_url=source_url,
                unique_hash=unique_hash,
                metadata={
                    'scraped_at': timezone.now().isoformat(),
                    'engine': engine_label
                }
            )
            items_created += 1

        # Push this run's new items to any configured external destinations.
        delivery_results = deliver_run_to_destinations(job, job_run)

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
            'urls_count': len(urls_visited),
            'agent_errors': agent_errors,
            'destinations': delivery_results,
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


def _maybe_cache_css_schema(job, agent_out, urls, use_js, timeout):
    """
    Derive a CSS schema from the agent's plan and cache it on the job so future runs
    skip the LLM. Only caches cheap, reproducible single-page list extractions, and
    only after verifying the schema reproduces a comparable number of rows.
    """
    from .scraping_engine import SelectorTester

    plan = agent_out.get('plan') or {}
    rows = agent_out.get('rows') or []

    # Only single-page lists are safely reproducible with static CSS (detail-link
    # following needs the agent's navigation).
    if not plan.get('is_list') or plan.get('follow_detail_links'):
        return
    container = plan.get('container_selector')
    if not container:
        return

    fields = {}
    for f in plan.get('fields', []):
        sel = f.get('css_selector')
        if not sel:
            return  # incomplete CSS -> don't cache
        fields[f['name']] = {'selector': sel, 'attr': f.get('attr', 'text'), 'type': 'string'}
    if not fields:
        return

    candidate = {'container': container, 'fields': fields}

    # Verify before trusting: the CSS schema must reproduce most of the agent's rows.
    result = asyncio.run(
        SelectorTester.test_selectors(urls[0], candidate, use_js_rendering=use_js)
    )
    found = result.get('total_found', 0) if result.get('success') else 0
    if found >= max(1, int(0.6 * len(rows))):
        job.configuration['selectors'] = candidate
        job.configuration['css_cached'] = True
        job.save(update_fields=['configuration', 'updated_at'])
        logger.info(
            f"Cached CSS schema for job {job.id} ({found} rows verified); "
            f"future runs skip the LLM"
        )
    else:
        logger.info(
            f"CSS schema not cached for job {job.id}: only {found} CSS rows "
            f"vs {len(rows)} agent rows"
        )


def deliver_run_to_destinations(job, job_run) -> list:
    """
    Push the items created in this run to every enabled destination on the job.

    Returns a list of per-destination result dicts (also stored on the run stats).
    A destination failure never fails the run — it's recorded and reported.
    """
    from .destinations import get_destination
    from .export_utils import flatten_items

    destinations = list(job.destinations.filter(enabled=True))
    if not destinations:
        return []

    items = list(job_run.items.all().order_by('created_at'))
    if not items:
        return [{'id': d.id, 'name': d.name, 'success': True, 'rows_delivered': 0,
                 'note': 'no new items'} for d in destinations]

    columns, rows = flatten_items(items)
    results = []
    for dest in destinations:
        try:
            handler = get_destination(dest.dest_type, dest.config)
            result = handler.deliver(columns, rows)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Destination {dest.id} ({dest.dest_type}) failed: {e}", exc_info=True)
            from .destinations.base import DeliveryResult
            result = DeliveryResult(success=False, error=str(e))

        dest.last_delivery_at = timezone.now()
        dest.last_status = 'success' if result.success else 'failed'
        dest.last_error = '' if result.success else (result.error or '')[:2000]
        if result.success:
            dest.total_rows_delivered += result.rows_delivered
        dest.save(update_fields=['last_delivery_at', 'last_status', 'last_error',
                                 'total_rows_delivered', 'updated_at'])

        results.append({
            'id': dest.id, 'name': dest.name, 'type': dest.dest_type,
            'success': result.success, 'rows_delivered': result.rows_delivered,
            'error': result.error,
        })
    return results


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
