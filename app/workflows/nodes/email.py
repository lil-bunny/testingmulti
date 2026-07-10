import logging

from app.services.pod_lifecycle.email_service import PodLifecycleEmailService
from app.tools.communication_metadata import stash_communication_id

logger = logging.getLogger(__name__)


def send_email(state):
    result = PodLifecycleEmailService().send_pod_reminder_from_state(state)
    patch = result.to_state_patch()
    if result.send_result:
        stash_communication_id(state, result.send_result)
    elif result.communication_id:
        state.data["communication_id"] = result.communication_id
    state.data.update(patch)
    return state
