"""Celery autodiscovery entrypoint: ``autodiscover_tasks([\"app.tasks\"])`` imports ``app.tasks.tasks``.

Side-effect imports register each ``@celery_app.task`` with the worker.
"""

from app.tasks.email import run_email_webhook  # noqa: F401
from app.tasks.reminders import trigger_workflow_reminder  # noqa: F401
from app.tasks.workflow_error_alerts import send_workflow_error_alert  # noqa: F401
from app.tasks.workflows import run_workflow_async  # noqa: F401
