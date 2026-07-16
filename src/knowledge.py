import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def _load(name):
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def _normalize_id(value):
    """Strips spaces/hyphens and case so a spoken/transcribed ID like 'SMP HL 500123'
    or 'smphl500123' still matches the stored 'SMP-HL-500123' - STT rarely reproduces
    the exact punctuation a caller reads out."""
    return re.sub(r"[^A-Za-z0-9]", "", value or "").upper()


_claims = {c["claim_id"]: c for c in _load("claims.json")["claims"]}
_claims_by_norm_id = {_normalize_id(cid): c for cid, c in _claims.items()}
_claims_by_norm_policy = {_normalize_id(c["policy_no"]): c for c in _claims.values()}
_policy_kb = _load("policy_kb.json")
_denial_templates = _load("denial_templates.json")["templates"]
_cashless_faq = _load("cashless_faq.json")["faqs"]
_document_checklist = _load("document_checklist.json")


def _humanize(term):
    return term.replace("_", " ")


def _build_policy_derived_faq():
    """Turns policy_kb.json facts into FAQ-style entries so coverage questions
    ("is cataract covered?") are searchable the same way cashless_faq.json is."""
    entries = []

    for sub in _policy_kb.get("sub_limits", []):
        condition = _humanize(sub["condition"])
        note = f" {sub['note']}" if sub.get("note") else ""
        entries.append({
            "q": f"is {condition} covered",
            "a": f"Yes, {condition} is covered up to Rs {sub['limit']:,}.{note}",
        })

    for exclusion in _policy_kb.get("exclusions", []):
        name = _humanize(exclusion)
        entries.append({
            "q": f"is {name} covered",
            "a": f"No, {name} is not covered. It is listed as an exclusion under your policy.",
        })

    if _policy_kb.get("exclusions"):
        names = ", ".join(_humanize(e) for e in _policy_kb["exclusions"])
        entries.append({
            "q": "what are the exclusions list of exclusions what is not covered",
            "a": f"The following are excluded under your policy: {names}.",
        })

    for wp in _policy_kb.get("waiting_periods", []):
        if wp["category"] == "specific_ailments":
            for example in wp.get("examples", []):
                name = _humanize(example)
                entries.append({
                    "q": f"what is the waiting period for {name}",
                    "a": f"{name.capitalize()} has a waiting period of {wp['months']} months under this policy.",
                })
        elif wp["category"] == "pre_existing_diseases":
            entries.append({
                "q": "what is the waiting period for pre existing disease",
                "a": f"Pre-existing diseases have a waiting period of {wp['months']} months under this policy.",
            })
        elif wp["category"] == "maternity":
            entries.append({
                "q": "what is the waiting period for maternity",
                "a": f"Maternity has a waiting period of {wp['months']} months under this policy.",
            })
        elif wp["category"] == "initial":
            entries.append({
                "q": "what is the initial waiting period",
                "a": (
                    f"There is an initial waiting period of {wp['days']} days from policy start, "
                    "during which no claims are covered except accidents."
                ),
            })

    cap = _policy_kb.get("room_rent_cap")
    if cap:
        entries.append({
            "q": "what is my room rent limit",
            "a": f"Your room rent limit is Rs {cap['amount']:,} per day. {cap['rule']}",
        })

    entries.append({
        "q": "what is my sum insured",
        "a": f"Your sum insured is Rs {_policy_kb['sum_insured']:,} for the policy year.",
    })
    entries.append({
        "q": "how many days of pre hospitalization expenses are covered",
        "a": f"Expenses from {_policy_kb['pre_hospitalization_days']} days before hospitalization are covered.",
    })
    entries.append({
        "q": "how many days of post hospitalization expenses are covered",
        "a": f"Expenses up to {_policy_kb['post_hospitalization_days']} days after discharge are covered.",
    })
    return entries


_policy_derived_faq = _build_policy_derived_faq()
_all_faq = _cashless_faq + _policy_derived_faq


def get_claim_status(claim_id=None, policy_no=None):
    if claim_id:
        claim = _claims_by_norm_id.get(_normalize_id(claim_id))
        if claim:
            return claim
    if policy_no:
        claim = _claims_by_norm_policy.get(_normalize_id(policy_no))
        if claim:
            return claim
    return None


def get_cashless_status(policy_no):
    claim = get_claim_status(policy_no=policy_no)
    if claim and claim["claim_type"] == "cashless":
        return claim
    return None


_STEM_SUFFIXES = ("ation", "ing", "age", "ed", "es", "s")


def _stem(word):
    for suffix in _STEM_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "what", "which", "who",
    "how", "do", "does", "did", "can", "could", "will", "would", "should",
    "i", "my", "me", "you", "your", "it", "of", "for", "in", "on", "at",
    "to", "and", "or", "if", "this", "that", "be", "am",
}


def _tokenize(text):
    # Stem so LLM-normalized paraphrases ("coverage" vs FAQ's "covered") still overlap,
    # and drop stopwords so generic "what is the" phrasing can't fake a match.
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {_stem(w) for w in words if w not in _STOPWORDS}


def get_policy_clause(query):
    query_tokens = _tokenize(query)
    best_score, best_answer = 0, None
    for faq in _all_faq:
        score = len(query_tokens & _tokenize(faq["q"]))
        if score > best_score:
            best_score, best_answer = score, faq["a"]
    # Require at least two overlapping content words - a single shared word (e.g. "surgery"
    # matching both "pet surgery" and the unrelated "cosmetic surgery" exclusion) is too weak
    # a signal and risks confidently returning the wrong record instead of admitting no match.
    if best_score >= 2:
        return {"found": True, "text": best_answer}
    return {"found": False, "text": None}


def _doc_labels(claim_type, doc_ids):
    catalog = {d["id"]: d["label"] for d in _document_checklist[claim_type]}
    return [catalog.get(doc_id, doc_id) for doc_id in doc_ids]


def document_label(claim_type, doc_id):
    return _doc_labels(claim_type, [doc_id])[0]


def get_denial_reason(claim_id):
    claim = get_claim_status(claim_id=claim_id)
    if not claim or not claim.get("denial_reason_code"):
        return {"found": False, "text": None}

    code = claim["denial_reason_code"]
    template = _denial_templates.get(code)
    if not template:
        return {"found": False, "text": None}

    reason = template["reason"]
    treatment = claim.get("treatment_type")

    if code == "SUBLIMIT_EXCEEDED" and treatment:
        sub_limit = next((s for s in _policy_kb["sub_limits"] if s["condition"] == treatment), None)
        if sub_limit:
            reason += f" For {treatment.replace('_', ' ')}, the limit is Rs {sub_limit['limit']:,}."
            if sub_limit.get("note"):
                reason += f" {sub_limit['note']}"
    elif code == "WAITING_PERIOD" and treatment:
        waiting = next(
            (w for w in _policy_kb["waiting_periods"] if treatment in w.get("examples", [])), None
        )
        if waiting:
            reason += f" For {treatment.replace('_', ' ')}, the waiting period is {waiting['months']} months."
    elif code == "EXCLUSION" and treatment in _policy_kb.get("exclusions", []):
        reason += f" Specifically, {treatment.replace('_', ' ')} is listed as an exclusion."
    elif code == "DOCUMENT_INSUFFICIENT" and claim.get("pending_documents"):
        labels = _doc_labels(claim["claim_type"], claim["pending_documents"])
        reason += f" Specifically, the following are missing: {', '.join(labels)}."

    text = f"{reason} {template['next_step']}"
    return {"found": True, "text": text, "denial_reason_code": code, "claim_id": claim["claim_id"]}


def document_checklist_ids(claim_type):
    return [d["id"] for d in _document_checklist[claim_type]]


def check_document_completeness(claim_id, additional_received=None):
    claim = get_claim_status(claim_id=claim_id)
    if not claim:
        return {"found": False}

    additional_received = additional_received or []
    required = document_checklist_ids(claim["claim_type"])
    still_pending = [d for d in claim.get("pending_documents", []) if d not in additional_received]
    received = [doc_id for doc_id in required if doc_id not in still_pending]
    return {
        "found": True,
        "claim_id": claim["claim_id"],
        "claim_type": claim["claim_type"],
        "missing": still_pending,
        "missing_labels": _doc_labels(claim["claim_type"], still_pending),
        "received_labels": _doc_labels(claim["claim_type"], received),
    }


def create_grievance_case(session_id, claimant_name, language, intent, claim_context, discussion_summary):
    return {
        "session_id": session_id,
        "claimant_name": claimant_name,
        "language": language,
        "intent": intent,
        "claim_context": claim_context,
        "discussion_summary": discussion_summary,
        "status": "routed_to_human",
    }
