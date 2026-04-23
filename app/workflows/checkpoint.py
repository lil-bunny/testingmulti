import atexit
from contextlib import ExitStack

from app.core.config import settings

from langgraph.checkpoint.postgres import PostgresSaver


_CHECKPOINTER = None
_EXIT_STACK = ExitStack()


def _build_checkpointer():
    saver_ctx = PostgresSaver.from_conn_string(settings.DATABASE_URL)
    saver = _EXIT_STACK.enter_context(saver_ctx)
    saver.setup()
    return saver


def get_checkpointer():
    global _CHECKPOINTER
    if _CHECKPOINTER is None:
        _CHECKPOINTER = _build_checkpointer()
    return _CHECKPOINTER


@atexit.register
def _close_checkpoint_resources():
    _EXIT_STACK.close()
