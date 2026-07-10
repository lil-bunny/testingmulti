"""Celery app entry for POD mail-free E2E — installs test stubs, then re-exports production app."""

from app.celery_app import celery_app  # noqa: F401

from tests.e2e.celery_worker_stubs import install_pod_e2e_stubs

install_pod_e2e_stubs()
