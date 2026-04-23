def process_pod_payload(payload: dict) -> dict:
    attachments = payload.get("attachments", [])
    has_attachments = bool(attachments)
    confidence = 0.9 if has_attachments else 0.0
    return {
        "success": has_attachments,
        "confidence_score": confidence,
        "pod_status": "PASS" if has_attachments else "MISSING",
    }
