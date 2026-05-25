"""Celery autodiscovery entrypoint: ``autodiscover_tasks([\"app.tasks\"])`` imports ``app.tasks.tasks``."""

from app.tasks.reminders import trigger_workflow_reminder  # noqa: F401
