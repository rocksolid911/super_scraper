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
        blocked_urls = []

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

            # Per-job proxy override (a URL or list); otherwise the engine falls
            # back to the global SCRAPER_CONFIG['PROXY_URLS'] pool.
            job_proxy = config.get('proxy')
            if isinstance(job_proxy, str):
                job_proxy = [job_proxy]

            # Deterministic CSS extraction (visual mode / cached selectors), one
            # browser lifecycle per run instead of a new event loop per URL.
            engine = ScrapingEngine(
                use_js_rendering=job.use_js_rendering,
                respect_robots_txt=job.respect_robots_txt,
                rate_limit=job.rate_limit,
                timeout=settings.SCRAPER_CONFIG['DEFAULT_TIMEOUT'],
                max_retries=settings.SCRAPER_CONFIG['MAX_RETRIES'],
                proxies=job_proxy
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
            blocked_urls = list(engine.blocked_urls)

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

        # A run that fetched no page and produced no row didn't really "succeed" —
        # surface why instead of reporting an empty success the user can't explain.
        run_error_message = ''
        if total_pages == 0 and items_created == 0:
            if blocked_urls:
                run_error_message = (
                    f"All {len(blocked_urls)} URL(s) were blocked by robots.txt, so nothing "
                    f"was fetched. Turn off 'Respect robots.txt' for this job to scrape anyway. "
                    f"Blocked: {', '.join(blocked_urls[:5])}"
                )
            else:
                run_error_message = (
                    "No pages could be fetched (every URL failed to load or returned empty). "
                    "Check the URL(s) and try toggling 'Use JS rendering'."
                )
        elif items_created == 0 and agent_errors:
            # Pages were visited but nothing was extracted *and* the agent hit errors
            # (e.g. a fetch timeout) — surface that instead of a misleading empty success.
            run_error_message = (
                "No rows were extracted. The page may have failed to load in time or "
                f"changed structure. Details: {str(agent_errors[0])[:300]}"
            )
        run_succeeded = not run_error_message

        # Change detection: index this run's content and diff it against the previous
        # run. Only successful runs are indexed, so a transient empty/failed run never
        # becomes a baseline that makes the next run look like a wholesale change.
        change = {}
        current_index = {}
        if run_succeeded:
            try:
                from . import monitoring
                current_index = monitoring.build_content_index(all_items)
                prev_run = monitoring.previous_indexed_run(job, job_run)
                change = monitoring.diff_indexes(
                    current_index, prev_run.content_index if prev_run else None
                )
            except Exception as e:  # noqa: BLE001 - never fail a run over diffing
                logger.warning(f"Change detection failed for job {job_id}: {e}")

        # Update job run
        job_run.status = JobRun.Status.SUCCESS if run_succeeded else JobRun.Status.FAILED
        job_run.finished_at = finished_at
        job_run.duration_seconds = duration
        job_run.items_scraped = items_created
        job_run.pages_visited = total_pages
        job_run.error_message = run_error_message
        job_run.errors_count = 0 if run_succeeded else 1
        job_run.content_index = current_index
        job_run.stats = {
            'total_items_found': len(all_items),
            'items_created': items_created,
            'items_duplicated': items_duplicated,
            'urls_visited': urls_visited,
            'urls_count': len(urls_visited),
            'blocked_urls': blocked_urls,
            'agent_errors': agent_errors,
            'destinations': delivery_results,
            'change': change,
        }
        job_run.save()

        # Update job statistics
        job.total_runs += 1
        if run_succeeded:
            job.successful_runs += 1
        else:
            job.failed_runs += 1
        job.total_items_scraped += items_created
        job.last_run_at = finished_at

        # Update next run time if scheduled
        if job.is_scheduled:
            job.next_run_at = calculate_next_run_time(job.schedule_config)

        job.save()

        # Fire change alerts when the content actually changed and the job opts in.
        # Never let a notification failure fail the run — record the outcome instead.
        if run_succeeded and job.notify_on_change and change.get('changed'):
            try:
                from .notifications import send_change_alert
                notify_results = send_change_alert(job, job_run, change)
                if notify_results:
                    job_run.stats['notifications'] = notify_results
                    job_run.save(update_fields=['stats'])
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Change alert failed for job {job_id}: {e}")

        if run_succeeded:
            logger.info(
                f"Job {job.name} completed successfully. "
                f"Scraped {items_created} items in {duration:.2f}s"
            )
        else:
            logger.warning(f"Job {job.name} produced no data: {run_error_message}")

        return {
            'success': run_succeeded,
            'job_id': job_id,
            'run_id': job_run.id,
            'items_scraped': items_created,
            'pages_visited': total_pages,
            'duration': duration,
            'error': run_error_message,
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


async def _preview_extract(url: str, prompt: str, use_js: bool, timeout: int):
    """Single-page LLM extraction for a dry-run preview: one fetch, plan, extract.

    Deliberately does NOT follow detail links or paginate — it just shows what the
    first page yields so the user can sanity-check before committing to a full run.
    """
    from .engines import get_fetch_engine
    from .engines.registry import fetch_with_fallback
    from .agent.llm import get_llm
    from .agent.state import ExtractionPlan, safe_field_name
    from .agent.graph import build_row_models, _truncate, absolutize_row_urls

    engine = get_fetch_engine()
    try:
        # Preview only samples the first page, so skip the full-page scroll for speed.
        fr = await fetch_with_fallback(engine, url, js=use_js, timeout=timeout,
                                       scan_full_page=False)
        if not fr.success or fr.is_empty:
            return [], (fr.error or 'Failed to fetch the page')
        sample = _truncate(fr.markdown or fr.html)

        planner = get_llm(role='planner').with_structured_output(ExtractionPlan)
        plan = await planner.ainvoke(
            "You are a web-scraping planner. Decide what columns to extract.\n\n"
            f"USER REQUEST:\n{prompt}\n\nPAGE SAMPLE (markdown):\n{sample}\n\n"
            "Return snake_case field names for the data the user asked for."
        )
        seen, names = set(), []
        for f in plan.fields:
            n = safe_field_name(f.name)
            while n in seen:
                n += "_x"
            seen.add(n)
            f.name = n
            names.append(n)
        if not names:
            return [], 'Could not determine columns to extract'

        ResultModel = build_row_models(names)
        extractor = get_llm(role='extractor').with_structured_output(ResultModel)
        col_desc = "\n".join(f"- {f.name}: {f.description}" for f in plan.fields)
        result = await extractor.ainvoke(
            "Extract structured rows from the page content below.\n\n"
            f"USER REQUEST:\n{prompt}\n\nCOLUMNS:\n{col_desc}\n\n"
            f"PAGE CONTENT (markdown):\n{sample}\n\n"
            "Return up to 8 rows. Use null for missing values. Do not invent data."
        )
        rows = [absolutize_row_urls(r.model_dump(), url) for r in result.rows][:8]
        return rows, None
    finally:
        await engine.close()


@shared_task
def preview_scrape_task(payload: dict) -> dict:
    """Bounded dry run: return up to 8 sample rows for a URL+prompt (or selectors).

    Persists nothing — used by the "Preview output" button so a user can see what a
    job would extract before creating/running it.
    """
    urls = payload.get('urls') or ([payload['url']] if payload.get('url') else [])
    urls = [u for u in urls if u]
    prompt = (payload.get('prompt') or '').strip()
    selectors = payload.get('selectors') or {}
    use_js = bool(payload.get('use_js_rendering'))
    timeout = settings.SCRAPER_CONFIG['DEFAULT_TIMEOUT']

    if not urls:
        return {'success': False, 'error': 'No URL provided', 'rows': [], 'columns': []}
    url = urls[0]
    err = None
    try:
        if selectors.get('fields'):
            from .scraping_engine import SelectorTester
            res = asyncio.run(SelectorTester.test_selectors(url, selectors, use_js))
            rows = (res.get('items') or [])[:8] if res.get('success') else []
            err = None if res.get('success') else res.get('error')
        elif prompt:
            rows, err = asyncio.run(_preview_extract(url, prompt, use_js, timeout))
        else:
            return {'success': False, 'error': 'Provide a prompt or selectors',
                    'rows': [], 'columns': []}

        columns, clean = [], []
        for r in rows:
            if not isinstance(r, dict):
                continue
            d = {k: v for k, v in r.items() if k != '_source_url'}
            clean.append(d)
            for k in d:
                if k not in columns:
                    columns.append(k)
        return {'success': True, 'url': url, 'columns': columns,
                'rows': clean, 'count': len(clean), 'error': err}
    except Exception as e:  # noqa: BLE001
        logger.error(f"Preview failed for {url}: {e}", exc_info=True)
        return {'success': False, 'error': str(e), 'rows': [], 'columns': []}


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
