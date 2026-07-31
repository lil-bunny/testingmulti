"""Activity log nodes for the ``ratecon`` workflow."""

from __future__ import annotations

from app.services.ratecon_activity_service import RateconActivityService


def record_ratecon_received_activity(state):
    ratecon_activity_service = RateconActivityService()
    ratecon_activity_service.record_received(state)
    return state


def record_ratecon_upload_activity(state):
    ratecon_activity_service = RateconActivityService()
    ratecon_activity_service.record_upload(state)
    return state
