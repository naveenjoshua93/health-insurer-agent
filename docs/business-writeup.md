# Sampoorna Health Secure — Claims Assistant: Business Writeup

## The problem

Health-insurance claims servicing is the single biggest driver of grievances, call-center cost, and churn for an
insurer or TPA. Three moments in a claimant's journey generate a disproportionate share of that friction:

1. **Before treatment** — "Is my cashless approved? Can I even use this hospital?" Time-critical, and the caller
   is often standing at an admission desk with a hospitalized family member.
2. **After treatment** — "What documents do I need, and is my file complete?" Document-heavy, and the single most
   common cause of delayed or rejected reimbursement is a missing discharge summary or PAN card.
3. **After adjudication** — "Why was I only paid part of what I claimed?" Emotionally charged, and the single
   biggest driver of formal grievances and IRDAI complaints when handled poorly.

A caller navigating these moments today typically waits on hold, repeats their claim number three times across
transfers, and — for the denial case — often can't get a plain-language answer to "why," only a form letter.

## What this PoC proves

A caller can tap **Call** inside the insurer's own app and resolve all three moments through natural conversation
in Hindi, Malayalam, or any of ten-plus Indian languages — without selecting a language, without navigating a
phone tree, and without repeating themselves if handed to a human.

## Why this needed to be built on Sarvam specifically

The India-specific capabilities aren't decorative here — they're load-bearing:

- **Auto-detected, code-mixed Indic speech.** A claimant who starts in Hindi and drifts into English mid-sentence
  ("mera claim reject ho gaya, why?") is normal, not an edge case. Saaras handles this natively.
- **Indic document OCR.** Discharge summaries and prescriptions from Indian hospitals are frequently in regional
  scripts. Sarvam Vision's doc-digitization reads them without a separate translation step.
- **A model that reasons in Indian languages, not just translates into them.** Sarvam-105B's tool-calling lets the
  same "which claims tool does this question need" decision work regardless of which language it's asked in.
- **Sovereign data handling.** Claims data, health information, and PAN details never leave an Indian-hosted
  stack — a real procurement requirement for regulated insurers, not a nice-to-have.

## The anti-hallucination guardrail (the compliance story)

The single most important architectural decision in this build: **the LLM never authors a coverage rule, a
monetary limit, or a denial reason.** Every regulated fact — a room-rent cap, a waiting period, a denial code —
is retrieved from a structured JSON knowledge base first; the AI's only job is to retrieve the right fact and
render it fluently in the caller's language. If a question falls outside that knowledge base, the assistant says
so and offers a human handoff, rather than guessing. This is the difference between a **claims-assistance layer
with guardrails** and a chatbot — and it's the reason a regulator or compliance officer can sign off on it.

## What a COO / Head of Claims should take from the numbers

The `/metrics` endpoint (viewable at `/static/audit.html`) tracks exactly what a claims-ops leader would ask for:

- **Containment rate** — the headline number: what fraction of calls resolve without a human agent.
- **Language-wise containment** — proof that the Indic capability isn't just a demo trick; it holds up per
  language.
- **Document-completeness-at-first-submission** — how often OCR correctly classifies an uploaded document on the
  first try, which is the number that predicts fewer resubmission cycles and faster claim closure.
- **Escalation quality** — whether every handoff to a human carried a usable case summary (claim context, what
  was discussed, why it escalated) rather than a cold transfer.
- **CSAT proxy** — a simple thumbs-up/down captured at the end of every call.

## What was deliberately left out, and why that's a feature

Every exclusion below was a considered call, not a shortcut:

- **No automated adjudication.** The assistant explains and de-escalates; a human still decides. This is the
  right scope for a PoC and the right scope for what a regulator will accept in production.
- **No RAG / vector store.** At one insurer's scale (a few hundred knowledge entries), semantic retrieval is
  over-engineering, and worse, it's the wrong tool for regulated content that must be exact, not merely similar.
  Deterministic JSON lookup is simpler, fully auditable, and demos identically. RAG is the named upgrade once the
  knowledge base scales to many products and many insurers.
- **No real-time/barge-in voice.** Turn-based voice trades conversational smoothness for build simplicity and an
  honest demo — the value here is the workflow, not shaving milliseconds off turn-taking. Pipecat is the named
  production upgrade path.
- **No custom orchestration framework (LangGraph).** Three intents and a couple of branches is a simple router; a
  few hundred lines of explicit Python is more legible and more debuggable than a graph framework, and it keeps
  the "agentic" property 100% Sarvam-native rather than borrowed from a third party.

## The production upgrade path, named up front

This PoC is deliberately lean, and the deck should say so explicitly rather than let a buyer assume the PoC *is*
the product:

| PoC choice | Production upgrade | Trigger to upgrade |
|---|---|---|
| Structured JSON knowledge | RAG / vector store | Multiple insurers, thousands of denial precedents |
| Explicit Python router | LangGraph specialist agents | Intents multiply beyond 3-4 |
| Turn-based voice | Pipecat real-time streaming | Conversational smoothness becomes the ask |
| In-app only | + Telephony (Twilio/Plivo) | Reach beyond app users (elderly relatives, low-end phones) |

**The right way to read this PoC:** it is a credible, specific proof that the full Sarvam stack — voice,
reasoning, translation, and document intelligence — can be orchestrated into one coherent, compliant claims
workflow in about a week. It is not a production system, and it doesn't pretend to be one.
