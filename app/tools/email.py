def send_email(to, subject, body):
    print(f"[EMAIL] to={to}, subject={subject}") #TO-DO



def ingest_email(payload):
    return {
        "attachments": payload.get("attachments", []),
        "thread_id": payload.get("thread_id", "thread-123"),
        "body": payload.get("body", ""),
    }