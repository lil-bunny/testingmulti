from dotenv import load_dotenv

load_dotenv(override=False)

from celery import Celery

from app.core.config import settings


celery_app = Celery(
    "freightx",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
)

# Redis: max countdown must stay *below* visibility_timeout (kombu/celery delayed-task semantics).
# No arbitrary +1 day: max countdown + expire grace (+ run/ack) matches ~50h cap for the 48h reminder.
if settings.CELERY_BROKER_URL.startswith("redis"):
    _max_reminder_s = max(settings.REMINDER_1_HOURS, settings.REMINDER_2_HOURS) * 3600
    _grace_s = settings.REMINDER_EXPIRE_GRACE_HOURS * 3600
    _exec_slack_s = 3600  # after ETA, worst-case run time + ack
    _redis_visibility_timeout = _max_reminder_s + _grace_s + _exec_slack_s
    celery_app.conf.broker_transport_options = {
        "visibility_timeout": _redis_visibility_timeout,
    }
    if settings.CELERY_RESULT_BACKEND.startswith("redis"):
        celery_app.conf.result_backend_transport_options = {
            "visibility_timeout": _redis_visibility_timeout,
        }

# Explicit imports keep task discovery predictable in simple deployments.
celery_app.autodiscover_tasks(["app.tasks"])
