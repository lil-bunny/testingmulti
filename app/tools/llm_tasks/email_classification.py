from app.tools.llm_client import LLMClientError, chat_json


def _heuristic_classify(body: str, has_attachments: bool) -> dict:
    lowered = (body or "").lower()
    is_reply = ("pod" in lowered and "request" not in lowered) or has_attachments
    return {
        "is_pod_reply_mail": is_reply,
        "is_pod_attached": has_attachments,
    }


def classify_email_for_pod(body: str, attachments: list | None = None) -> dict:
    attachments = attachments or []
    has_attachments = bool(attachments)

    system_prompt = (
        "Classify freight emails for POD workflow routing.\n"
        "Return strict JSON only with keys:\n"
        "- is_pod_reply_mail (boolean)\n"
        "- is_pod_attached (boolean)\n"
    )
    user_prompt = (
        f"Email body:\n{body or ''}\n\n"
        f"Attachment count: {len(attachments)}\n"
    )

    try:
        result = chat_json(system_prompt=system_prompt, user_prompt=user_prompt)
        return {
            "is_pod_reply_mail": bool(result.get("is_pod_reply_mail")),
            "is_pod_attached": bool(result.get("is_pod_attached")),
        }
    except LLMClientError:
        return _heuristic_classify(body, has_attachments)
