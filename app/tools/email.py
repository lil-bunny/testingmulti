from app.services.unipile_service import Unipile

def send_email(to, subject, body):
    print(f"[EMAIL] to={to}, subject={subject}") #TO-DO

def ingest_email(payload):

    return {
        "attachments": payload.get("attachments"),
        "thread_id": payload.get("thread_id"),
        "body": payload.get("body"),
        "subject": payload.get("subject"),
        "has_attachments": payload.get("has_attachments"),
        "role":payload.get("role"),
        "email_id": payload.get("email_id"),
        "account_id": payload.get("account_id"),
        "provider_id": payload.get("provider_id"),
        "message_id": payload.get("message_id"),
        "from_attendee": payload.get("from_attendee"),
        "to_attendees": payload.get("to_attendees"),
        "cc_attendees": payload.get("cc_attendees"),
        "in_reply_to": payload.get("in_reply_to"),
        "date": payload.get("date")
    }


def get_email_attachments(email_id, attachment_id, account_id):
    unipile = Unipile()
    file_content = unipile.get_email_attachment(email_id, attachment_id, account_id)
    return file_content