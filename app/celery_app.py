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
)

# autodiscover_tasks(["app.tasks"]) loads `app.tasks.tasks` by convention, not
# `app.tasks.reminders` — import reminder tasks explicitly so they register.
celery_app.autodiscover_tasks(["app.tasks"], related_name="reminders", force=True)
