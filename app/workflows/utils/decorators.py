from functools import wraps

from app.core.logger import get_logger
from app.domain.error_catalog import ErrorCategory, SystemError, workflow_error_payload
from app.domain.state import WorkflowState
from app.exceptions import WorkflowException

logger = get_logger(__name__)


def _apply_node_error(state: WorkflowState, error_payload: dict) -> dict:
    if not isinstance(state.data, dict):
        state.data = {}
    state.data["error"] = error_payload
    return {"data": state.data}


def safe_node(node_func):
    """
    Wraps LangGraph node functions to catch exceptions.
    Mutates the state to include an ``error`` dict so the builder router can intercept it.
    """

    @wraps(node_func)
    def wrapper(state: WorkflowState, *args, **kwargs):
        try:
            return node_func(state, *args, **kwargs)
        except WorkflowException as e:
            logger.warning(
                "Node %s failed: error_code=%s message=%s",
                node_func.__name__,
                e.error_code,
                e.message,
            )
            error_payload = workflow_error_payload(
                code=e.error_code,
                message=e.message,
                category=e.error_category,
            )
        except Exception:
            logger.exception("Node %s failed unexpectedly", node_func.__name__)
            error_payload = workflow_error_payload(
                code=SystemError.UNEXPECTED_NODE_FAILURE.value,
                message=SystemError.UNEXPECTED_NODE_FAILURE.description,
                category=ErrorCategory.SYSTEM,
            )
        return _apply_node_error(state, error_payload)

    return wrapper
