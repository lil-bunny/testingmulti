"""Celery autodiscovery entrypoint: ``autodiscover_tasks([\"app.tasks\"])`` imports ``app.tasks.tasks``."""

from app.tasks.reminders import trigger_pod_reminder  # noqa: F401
