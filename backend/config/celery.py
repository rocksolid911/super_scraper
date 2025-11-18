"""
Celery configuration for Universal AI Web Scraper.
"""
import os
from celery import Celery
from celery.schedules import crontab

# Set the default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('super_scraper')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

# Configure periodic tasks
app.conf.beat_schedule = {
    'check-scheduled-jobs': {
        'task': 'apps.scraper.tasks.check_scheduled_jobs',
        'schedule': crontab(minute='*/5'),  # Check every 5 minutes
    },
    'cleanup-old-job-runs': {
        'task': 'apps.scraper.tasks.cleanup_old_job_runs',
        'schedule': crontab(hour=2, minute=0),  # Daily at 2 AM
    },
}


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task for testing Celery setup."""
    print(f'Request: {self.request!r}')
