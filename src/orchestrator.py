import json
from src.sarvam import llm
from src.sarvam import translate as translate_mod
from src import knowledge

RETRY_TEXT = (
    "I'm sorry, I didn't quite get that. Could you rephrase your question or give me a bit more detail?"
)

FALLBACK_TEXT = (
    "I'm still not able to confirm that from what I have on file. "
    "Let me connect you to an agent who can help."
)

ESCALATION_NOTICE = " I've logged this and I'm connecting you to a human agent who can help further."

PROCESSING_FILLER_TEXT = "Okay, let me check that for you. One moment."

FAILED_ATTEMPT_LIMIT = 2

SYSTEM_PROMPT = (
    "You are the Health Secure Assistant, a claims assistant for Sampoorna Health Insurance. Use the available tools to answer the "
    "caller's question using only retrieved facts - never invent coverage details, limits, or denial reasons. "
    "If the caller's request is incomplete or ambiguous - for example they haven't given a claim ID or policy "
    "number yet, or it's unclear what they're asking about - do not call a tool and do not guess. Instead, reply "
    "directly with a short, specific follow-up question that asks for exactly what is missing (e.g. 'Could you "
    "share your claim ID or policy number?'). This is a normal, resolved part of the conversation, not a failure. "
    "Call create_grievance_case immediately, without trying other tools first, if the caller: explicitly asks "
    "for a human agent; sounds distressed or upset; raises anything out of scope or high-stakes (medical "
    "advice, legal threats, fraud allegations, IRDAI or ombudsman complaints); or gives identity details "
    "(claim ID or policy number) that don't seem to resolve to anything. If the caller is asking about a "
    "claim denial or being paid less than they claimed, call get_denial_reason first so the specific reason "
    "can be explained before any escalation."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_claim_status",
            "description": "Look up a claim's status by claim ID or policy number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "claim_id": {"type": "string"},
                    "policy_no": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cashless_status",
            "description": "Look up the status of a cashless pre-authorization by policy number.",
            "parameters": {
                "type": "object",
                "properties": {"policy_no": {"type": "string"}},
                "required": ["policy_no"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_policy_clause",
            "description": (
                "Look up an answer to a general cashless, coverage, or policy question. "
                "Pass a short normalized question capturing what the caller is asking."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_denial_reason",
            "description": "Look up why a claim was denied or paid less than claimed.",
            "parameters": {
                "type": "object",
                "properties": {"claim_id": {"type": "string"}},
                "required": ["claim_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_document_completeness",
            "description": "Check which required documents are still missing for a reimbursement claim.",
            "parameters": {
                "type": "object",
                "properties": {"claim_id": {"type": "string"}},
                "required": ["claim_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_grievance_case",
            "description": "Create a grievance case and escalate the session to a human agent.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    },
]


def _track_active_claim(session, result):
    claim_id = result.get("claim_id") if isinstance(result, dict) else None
    if claim_id:
        session["active_claim_id"] = claim_id


def _make_grievance(session, intent):
    grievance = knowledge.create_grievance_case(
        session_id=session["session_id"],
        claimant_name=session.get("claimant_name"),
        language=session.get("language"),
        intent=intent,
        claim_context=session.get("active_claim_id"),
        discussion_summary=[m["content"] for m in session.get("messages", []) if m.get("role") == "user"],
    )
    session["last_grievance"] = grievance
    return grievance


def _execute_tool(name, args, session):
    if name == "get_claim_status":
        return knowledge.get_claim_status(claim_id=args.get("claim_id"), policy_no=args.get("policy_no")) or {"found": False}
    if name == "get_cashless_status":
        return knowledge.get_cashless_status(policy_no=args.get("policy_no")) or {"found": False}
    if name == "get_policy_clause":
        return knowledge.get_policy_clause(args.get("query", ""))
    if name == "get_denial_reason":
        return knowledge.get_denial_reason(args.get("claim_id"))
    if name == "check_document_completeness":
        return knowledge.check_document_completeness(args.get("claim_id"))
    if name == "create_grievance_case":
        return _make_grievance(session, args.get("reason"))
    raise ValueError(f"Unknown tool: {name}")


def completeness_text(result):
    if not result.get("found"):
        return "I couldn't find that claim."
    received, missing = result.get("received_labels", []), result.get("missing_labels", [])
    if not missing:
        return "All your required documents have been received. Your file is complete."
    parts = []
    if received:
        parts.append(f"Your {' and '.join(received)} have been received")
    verb = "is" if len(missing) == 1 else "are"
    parts.append(f"but your {' and '.join(missing)} {verb} still missing")
    return ", ".join(parts) + "."


def upload_confirmation_text(document_id, completeness):
    if not completeness.get("found"):
        return "I couldn't find that claim."
    if document_id == "unknown":
        prefix = "I couldn't recognize that document from the scan."
    else:
        label = knowledge.document_label(completeness["claim_type"], document_id)
        prefix = f"Your {label} has been received."
    missing = completeness.get("missing_labels", [])
    if not missing:
        return f"{prefix} Your file is now complete."
    verb = "is" if len(missing) == 1 else "are"
    return f"{prefix} Your {' and '.join(missing)} {verb} still missing."


def _english_text_for_tool_result(name, result):
    """Deterministic English sentence for a tool result - no LLM composition needed.
    Returns None when the tool found nothing, so the caller can treat it as an unresolved attempt."""
    if name in ("get_claim_status", "get_cashless_status"):
        if not result or result.get("found") is False:
            return None
        status = result["status"].replace("_", " ")
        text = f"Your claim {result['claim_id']} is currently {status}."
        if result["status"] == "partially_paid":
            text += f" Rs {result['amount_approved']:,} was approved out of Rs {result['amount_claimed']:,} claimed."
        elif result["status"] == "approved":
            text += f" Rs {result['amount_approved']:,} was approved."
        return text

    if name == "get_policy_clause":
        return result["text"] if result.get("found") else None

    if name == "get_denial_reason":
        return f"For claim {result['claim_id']}: {result['text']}" if result.get("found") else None

    if name == "check_document_completeness":
        return f"For claim {result['claim_id']}: {completeness_text(result)}" if result.get("found") else None

    if name == "create_grievance_case":
        return "I've logged this and I'm connecting you to a human agent who will follow up with you."

    return None


def classify_uploaded_document(claim_type, ocr_text):
    """Cheap tool-forced classification of OCR'd document text against the checklist for this claim type."""
    checklist_ids = knowledge.document_checklist_ids(claim_type)
    tools = [{
        "type": "function",
        "function": {
            "name": "classify_document",
            "description": "Classify which required document type this OCR text corresponds to.",
            "parameters": {
                "type": "object",
                "properties": {
                    "document_id": {"type": "string", "enum": checklist_ids + ["unknown"]}
                },
                "required": ["document_id"],
            },
        },
    }]
    messages = [
        {"role": "system", "content": "You classify scanned insurance documents from their OCR text."},
        {"role": "user", "content": f"OCR text:\n{ocr_text[:1500]}\n\nWhich document type is this?"},
    ]
    resp = llm.chat(
        messages, tools=tools,
        tool_choice={"type": "function", "function": {"name": "classify_document"}},
        max_tokens=200, reasoning_effort="low",
    )
    message = resp["choices"][0]["message"]
    if not message.get("tool_calls"):
        return "unknown"
    try:
        args = json.loads(message["tool_calls"][0]["function"]["arguments"])
        return args.get("document_id", "unknown")
    except (json.JSONDecodeError, TypeError):
        return "unknown"


def run_turn(session, transcript, response_language):
    messages = session.setdefault("messages", [])
    if not messages:
        messages.append({"role": "system", "content": SYSTEM_PROMPT})
    messages.append({"role": "user", "content": transcript})

    tool_response = llm.chat(messages, tools=TOOLS, tool_choice="auto", max_tokens=400, reasoning_effort="low")
    message = tool_response["choices"][0]["message"]

    resolved = False
    action = None
    reply_en = None

    if message.get("tool_calls"):
        tool_call = message["tool_calls"][0]
        tool_name = tool_call["function"]["name"]
        try:
            tool_args = json.loads(tool_call["function"]["arguments"])
        except (json.JSONDecodeError, TypeError):
            tool_args = {}

        result = _execute_tool(tool_name, tool_args, session)
        _track_active_claim(session, result)
        reply_en = _english_text_for_tool_result(tool_name, result)

        if tool_name == "create_grievance_case":
            # An explicit immediate-escalation trigger (§4.11) - not a failed attempt.
            action = "ESCALATE"
            resolved = True
        elif reply_en is not None:
            resolved = True
            if tool_name == "get_denial_reason" and result.get("found"):
                _make_grievance(session, intent="denial_explanation")
                reply_en += ESCALATION_NOTICE
                action = "ESCALATE"

        messages.append({"role": "assistant", "tool_calls": message["tool_calls"]})
        messages.append({"role": "tool", "tool_call_id": tool_call["id"], "content": json.dumps(result, default=str)})
    elif message.get("content"):
        # No tool call, but the model has something to say - almost always a legitimate
        # clarifying follow-up question (e.g. "what's your claim ID?"). That's a normal,
        # resolved conversational turn, not a failed attempt - asking it shouldn't burn
        # through the escalation budget.
        resolved = True
        reply_en = message["content"]

    if resolved:
        session["failed_attempts"] = 0
    else:
        # A tool was called but found nothing - a genuinely unresolved attempt (§4.9),
        # not an immediate-trigger escalation. Give one retry before escalating.
        session["failed_attempts"] = session.get("failed_attempts", 0) + 1
        if session["failed_attempts"] >= FAILED_ATTEMPT_LIMIT:
            _make_grievance(session, intent="repeated_unresolved_question")
            reply_en = FALLBACK_TEXT
            action = "ESCALATE"
        else:
            reply_en = RETRY_TEXT

    reply_localized = translate_mod.translate(reply_en, source_language_code="en-IN", target_language_code=response_language)
    messages.append({"role": "assistant", "content": reply_en})

    return {"assistant_text": reply_localized, "assistant_text_en": reply_en, "action": action}
