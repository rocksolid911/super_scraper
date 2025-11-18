"""
Scraper app signals.
"""
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from .models import JobRun, ScrapeJob
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender=JobRun)
def update_job_stats_on_run_complete(sender, instance, created, **kwargs):
    """
    Update job statistics when a run completes.
    This is a safety net in case the task doesn't update stats properly.
    """
    if not created and instance.is_completed:
        job = instance.job

        # Recalculate stats from all runs
        all_runs = job.runs.all()
        total_runs = all_runs.count()
        successful_runs = all_runs.filter(status=JobRun.Status.SUCCESS).count()
        failed_runs = all_runs.filter(status=JobRun.Status.FAILED).count()
        total_items = sum(run.items_scraped for run in all_runs)

        # Only update if there's a discrepancy
        if (job.total_runs != total_runs or
            job.successful_runs != successful_runs or
            job.failed_runs != failed_runs or
            job.total_items_scraped != total_items):

            job.total_runs = total_runs
            job.successful_runs = successful_runs
            job.failed_runs = failed_runs
            job.total_items_scraped = total_items
            job.save(update_fields=[
                'total_runs', 'successful_runs',
                'failed_runs', 'total_items_scraped'
            ])

            logger.info(f"Updated stats for job {job.id}")


@receiver(pre_delete, sender=ScrapeJob)
def cancel_running_jobs_on_delete(sender, instance, **kwargs):
    """
    Cancel any running jobs when a ScrapeJob is deleted.
    """
    running_runs = instance.runs.filter(
        status__in=[JobRun.Status.PENDING, JobRun.Status.RUNNING]
    )

    for run in running_runs:
        if run.task_id:
            try:
                from celery import current_app
                current_app.control.revoke(run.task_id, terminate=True)
                logger.info(f"Cancelled task {run.task_id} for deleted job {instance.id}")
            except Exception as e:
                logger.error(f"Failed to cancel task {run.task_id}: {e}")
