from app.tools.email import send_email as send_email_tool
from app.tools.email import ingest_email as ingest_email_tool
from app.tools.llm_tasks.email_classification import classify_email_for_pod
from app.services.reminder_scheduler import schedule_initial_pod_reminders


def send_email(state):
    send_email_tool(
        state.data.get("to"),
        state.data.get("subject", "POD Request"),
        state.data.get("body", "")
    )
    schedule_initial_pod_reminders(state.data)

    return state


def ingest_email(state):
    result = ingest_email_tool(state.data)

    state.data.update(result)

    return state


def classify_inbound_email(state):
    body = state.data.get("body") or ""
    attachments = state.data.get("attachments") or []
    classification = classify_email_for_pod(body=body, attachments=attachments)
    state.data["is_pod_reply_mail"] = classification["is_pod_reply_mail"]
    state.data["is_pod_attached"] = classification["is_pod_attached"]
    return state