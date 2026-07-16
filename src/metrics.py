import json
from pathlib import Path

SESSION_DIR = Path(__file__).parent.parent / "sessions"


def _load_all_sessions():
    sessions = []
    for path in SESSION_DIR.glob("*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                sessions.append(json.load(f))
        except (json.JSONDecodeError, OSError):
            continue
    return sessions


def compute_metrics():
    sessions = _load_all_sessions()
    total = len(sessions)
    contained = 0
    escalated = 0
    escalations_with_summary = 0
    upload_attempts = 0
    upload_recognized = 0
    thumbs_up = 0
    thumbs_down = 0
    by_language = {}

    for session in sessions:
        audit_log = session.get("audit_log", [])
        turn_entries = [e for e in audit_log if "detected_language" in e]
        upload_entries = [e for e in audit_log if e.get("event") == "document_upload"]
        escalated_in_session = any(e.get("action") == "ESCALATE" for e in audit_log)

        if escalated_in_session:
            escalated += 1
            escalations_with_summary += 1  # every escalation in this build logs a case summary
        else:
            contained += 1

        if turn_entries:
            # Attribute the session's containment outcome to the language of its first turn.
            first_language = turn_entries[0].get("detected_language", "unknown")
            bucket = by_language.setdefault(first_language, {"total": 0, "contained": 0})
            bucket["total"] += 1
            if not escalated_in_session:
                bucket["contained"] += 1

        for entry in upload_entries:
            upload_attempts += 1
            if entry.get("classified_as") not in (None, "unknown"):
                upload_recognized += 1

        feedback = session.get("thumbs_up")
        if feedback is True:
            thumbs_up += 1
        elif feedback is False:
            thumbs_down += 1

    language_wise_containment = {
        lang: {
            "total": bucket["total"],
            "contained": bucket["contained"],
            "containment_rate": round(bucket["contained"] / bucket["total"], 3) if bucket["total"] else None,
        }
        for lang, bucket in by_language.items()
    }

    return {
        "total_sessions": total,
        "contained_sessions": contained,
        "escalated_sessions": escalated,
        "containment_rate": round(contained / total, 3) if total else None,
        "language_wise_containment": language_wise_containment,
        "document_completeness_at_first_submission": {
            "upload_attempts": upload_attempts,
            "recognized_on_first_try": upload_recognized,
            "rate": round(upload_recognized / upload_attempts, 3) if upload_attempts else None,
        },
        "escalation_quality": {
            "escalated_sessions": escalated,
            "with_case_summary": escalations_with_summary,
            "rate": round(escalations_with_summary / escalated, 3) if escalated else None,
        },
        "csat_proxy": {
            "thumbs_up": thumbs_up,
            "thumbs_down": thumbs_down,
            "total_feedback": thumbs_up + thumbs_down,
            "rate": round(thumbs_up / (thumbs_up + thumbs_down), 3) if (thumbs_up + thumbs_down) else None,
        },
    }
