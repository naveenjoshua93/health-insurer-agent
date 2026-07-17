# Sampoorna Health Secure — Claims & Grievance Assistant (PoC)

A multilingual, voice-based health-insurance claims assistant built on Sarvam AI's API stack. A caller taps **Call**
inside the (fictional) Sampoorna Health Insurance app and talks to an AI assistant, in their own Indian language,
about three of the highest-friction moments in a claims journey: cashless pre-authorization, reimbursement
document completeness, and denial/short-payment explanation.

**This is a proof-of-concept for a Sarvam AI Pre-Sales Engineer technical assignment.** All insurer, policy, and
claimant data is fictional.

**Live demo:** https://sarvam-claims-poc.onrender.com
**Business case deck:** [`docs/business-case-writeup.pdf`](docs/business-case-writeup.pdf)

---

## The problem this solves

Indian health insurers processed **3.26 crore claims** against **₹1.1L crore** in premium in FY25. Every claim
generates calls at three distinct, high-friction moments — and each one happens in a language an English-first
system handles badly:

1. **Cashless, before treatment** — "Is my father's hospital covered? How long will approval take?" Anxious, and
   often asked from a hospital admission desk.
2. **Reimbursement, after treatment** — "I paid myself — how do I claim it back? What documents do I need?"
   Document-heavy; the single most common cause of delay is a missing discharge summary or PAN card.
3. **Denial, after adjudication** — "Why was I only paid half of what I claimed?" Emotionally charged, and the
   single biggest driver of formal grievances when handled poorly.

Today these calls are handled by human agents (**₹40-80 per call**, hard to staff 24/7 in every language), IVR
menus (frustrating, can't read documents or reason), or English-first chatbots (leave out most of the country,
still can't handle documents). All three let the claimant down, so people fall back on costly human agents anyway.

## Why AI, why now

This isn't a general AI problem — it's an India-specific one. A generic English-first stack can't do any of the
following well enough for this use case:

- **Understand how India speaks** — code-mixed speech ("mera claim reject ho gaya, why?") is normal, not an edge
  case, for a claimant calling in under stress.
- **Reason through the claim, not just translate** — the same "which claims question is this" decision needs to
  work identically regardless of which of 22+ languages it's asked in.
- **Read Indian documents** — discharge summaries and prescriptions from Indian hospitals are frequently
  handwritten or in regional scripts.
- **Keep sensitive health data inside India** — sovereign data handling is a real procurement requirement for
  regulated insurers, not a nice-to-have.

## Why Sarvam specifically

| Capability | Sarvam API | Role in this build |
|---|---|---|
| Understands how India speaks | **Saaras** (STT, `saaras:v3`) | Listens and transcribes in 22 languages, including mixed speech like Hindi-English, auto-detecting the spoken language |
| Speaks back naturally | **Bulbul** (TTS) | Replies in the caller's own language |
| Reasons through the claim | **Sarvam-105B** (Chat Completions, tool-calling) | Decides which claims tool a question needs — cashless status, coverage, denial reason — in plain words |
| Reads Indian documents | **Sarvam Vision** (doc-digitization) | Reads bills, prescriptions, and discharge summaries — even handwritten, in regional scripts |
| Localizes retrieved facts | **Sarvam-Translate** | Renders an English-authored fact into the caller's language — fast, deterministic, no reasoning tax |

**A build note on latency and cost:** Sarvam-105B produces a chain-of-thought before any answer, even at
`reasoning_effort: "low"` — several hundred tokens for what should be a one-sentence reply. Rather than pay that
cost on every turn, the orchestrator uses Sarvam-105B **only** to decide which tool to call (a cheap, ~50-150
token decision on the fast path), then renders the retrieved fact via the lightweight Sarvam-Translate API
instead of asking the reasoning model to compose the explanation. This keeps regulated facts (denial reasons,
coverage limits) exactly as authored, and keeps each turn fast and bounded.

## Architecture overview

```
Caller (insurer app, voice)
   │
   ▼
Saaras (STT) — transcribes, auto-detects language + code-mixing
   │
   ▼
Orchestrator + Sarvam-105B (tool-calling)
   │  fast path: known question → retrieve exact fact → Sarvam-Translate localizes it (no reasoning tax)
   │  reasoning path: unusual question → Sarvam-105B reasons over the grounded facts
   ▼
┌──────────────────┬──────────────────────┬─────────────────────┐
│ Intelligence      │ Knowledge & data     │ Document layer       │
│ Sarvam-105B +     │ knowledge.py:        │ Sarvam Vision:        │
│ Sarvam-Translate  │ claims, policy KB,   │ OCR → classify →       │
│ - never invents   │ denial templates,    │ completeness check      │
│   facts           │ document checklist   │                          │
└──────────────────┴──────────────────────┴─────────────────────┘
   │
   ▼
Escalation & audit (cross-cutting) — immediate triggers (denial, human request, distress) +
2-failed-attempt catch-all → create_grievance_case, every turn logged to an audit trail
   │
   ▼
Bulbul (TTS) — speaks the reply in the caller's language
```

See [`docs/architecture-diagram.svg`](docs/architecture-diagram.svg) for the full visual diagram and
[`docs/technical-architecture.md`](docs/technical-architecture.md) for the deep technical writeup (turn
lifecycle, tool contracts, session model, voice UX design).

### The core design decision: retrieve-then-explain

**The LLM never authors a coverage rule, a monetary limit, or a denial reason.** It only picks which tool to
call; a deterministic Python lookup retrieves the fact, and a fixed template renders it before translation. If a
question falls outside the knowledge base, the assistant says so and escalates, rather than guessing. Every
resolved reply is tagged with the record it came from (e.g. "sourced from claim CL-1003"), so a reviewer can
verify an answer was retrieved, not invented — this is the difference between a claims-assistance layer with
guardrails and a chatbot.

### What adversarial testing found and fixed

A demo is easy; making it safe and honest for real claims is the engineering. Three subtle failures surfaced
under deliberate testing — none were crashes, all were wrong answers that looked right:

| What broke | How it was fixed |
|---|---|
| A question about "pet surgery" matched the human "cosmetic surgery" exclusion — the right *kind* of record, retrieved wrongly | Raised the match threshold so a single shared word no longer counts; a match needs two or more overlapping terms, or one genuinely specific term |
| Asked for the weather or a joke, the model sometimes just answered — breaking character | Added an explicit out-of-scope catch-all: anything unrelated to the caller's policy, claim, or documents now escalates to a human by rule |
| The escalation trigger for denials/disputes fired unreliably on some phrasings | Made the trigger deterministic — denials, disputes, and explicit human requests escalate by fixed rule, not model judgment |

The takeaway isn't the three bugs — it's that a probabilistic system needs a standing adversarial test pass, not
a one-time check.

## What's out of scope (deliberately)

No real telephony (toll-free is a named phase-2), no live claims-system integration (runs on seeded mock data),
no RAG/vector store (one insurer's knowledge base fits in context; RAG is the named upgrade once it spans many
products and insurers), no LangGraph/Pipecat orchestration frameworks (three intents is a simple router, not a
graph). See `docs/business-case-writeup.pdf` (slide 13) for the full "where the PoC stops, how it gets to
production" table, and `docs/business-writeup.md` for supporting rationale.

---

## Repository structure

```
/README.md
/run.py                     # entry point: `python run.py`
/render.yaml                 # Render deployment config
/src
  requirements.txt
  .env.example
  /data                      # claims.json, policy_kb.json, denial_templates.json, cashless_faq.json, document_checklist.json
  /sarvam                    # saaras.py, bulbul.py, translate.py, llm.py, vision.py, live_stt.py — one wrapper per Sarvam API
  knowledge.py                 # deterministic JSON lookups + English answer assembly (the "retrieve" half of retrieve-then-explain)
  orchestrator.py               # the turn loop: tool-selection call -> deterministic lookup -> translate -> escalation rules
  metrics.py                     # aggregates session files into containment/escalation/CSAT metrics
  app.py                           # FastAPI endpoints, serves /static
  /static                           # vanilla HTML/CSS/JS frontend (home, call, upload, escalation, audit screens)
/scripts
  generate_sample_documents.py       # synthesizes sample claim documents for the OCR demo
/sessions                    # JSON-file session storage (gitignored)
/docs
  business-case-writeup.pdf       # the business case deck (customer-ready, 19 slides)
  business-writeup.md           # supporting written rationale
  technical-architecture.md      # deep technical reference
  architecture-diagram.svg        # system diagram
```

## Setup & run

1. **Prerequisites:** Python 3.11+, a Sarvam API key ([dashboard.sarvam.ai](https://dashboard.sarvam.ai/)).
2. **Clone and enter the repo**, then:
   ```bash
   pip install -r src/requirements.txt
   cp src/.env.example .env   # then edit .env and set SARVAM_API_KEY=...
   ```
3. **Run:**
   ```bash
   python run.py
   ```
4. Open **http://localhost:8000** in a browser that has microphone access (Chrome/Edge recommended).

### A note on corporate proxies
If you're behind a corporate TLS-intercepting proxy and see `SSL: CERTIFICATE_VERIFY_FAILED` errors, install
`pip-system-certs` (`pip install pip-system-certs`) so Python trusts your OS certificate store. Not needed on Render.

## Demo script

- **Moment 1 (cashless):** Tap Call, ask *"Will my father's hospital be covered?"* or *"Is ambulance covered?"* —
  answered from `cashless_faq.json` / `policy_kb.json`, translated into whatever language you spoke.
- **Moment 2 (reimbursement):** Ask about reimbursement documents for claim CL-1003. When the assistant flags
  missing documents, a simulated SMS toast appears — tap it, upload a photo of a document (sample images in
  [`src/data/documents/`](src/data/documents/)), and watch the completeness verdict update.
- **Moment 3 (denial):** Ask why claim CL-1004 was paid less than claimed. The assistant explains the specific
  reason (room-rent cap) and automatically hands off to a human agent with a logged case summary — visible at
  `/static/audit.html`.

Seeded claims are in [`src/data/claims.json`](src/data/claims.json) — six claims spanning pending, approved,
queried, partially-paid, and rejected states. Try the same questions in Hindi or Malayalam to see the
multilingual path — the assistant auto-detects the spoken language per turn.

## API surface (backend)

| Endpoint | Purpose |
|---|---|
| `POST /session` | Start a new call session |
| `POST /turn` | Submit one turn of caller audio, get back transcript + reply + audio + any action |
| `POST /document` | Upload a scanned document for OCR + completeness check |
| `POST /session/{id}/language` | Override the response language mid-call |
| `POST /session/{id}/feedback` | Record a thumbs up/down (CSAT proxy) |
| `GET /session/{id}` | Session status (active claim, last grievance case) |
| `GET /audit/{id}` | Full turn-by-turn audit log for a session |
| `GET /sessions` | List recent sessions (for the audit viewer) |
| `GET /metrics` | Aggregate containment rate, language-wise containment, doc-recognition rate, escalation quality, CSAT proxy |

## Business case, in brief

On a multi-minute claims call, AI (~₹15-30) and a human agent (~₹40-50) are broadly comparable per call — the
honest number, not an inflated one. The real value is elsewhere, and it's larger:

- **Available 24/7, in every language** — no human agent answers in Malayalam at 2am.
- **Deflects the simple, short calls** — pure status and cashless-info calls are quick and cheap for AI, freeing
  human agents for the hard cases.
- **Removes rework** — an estimated **1 in 3 document resubmission cycles** avoided by catching a missing
  document on the very first call, each of which otherwise costs several follow-up calls and weeks of delay.
- **Fewer grievances, better retention** — clear answers in the caller's own language reduce disputes.

Full figures, assumptions, and the phased GTM path (paid pilot → prove metrics → production rollout → scale to
the full servicing layer) are in `docs/business-case-writeup.pdf`.

## Production upgrade path (named, not built)

- **RAG / vector store** once the knowledge base scales past one insurer's ~80 entries.
- **LangGraph** for specialist sub-agents (cashless / reimbursement / compliance) once intents multiply.
- **Pipecat** (`SarvamSTTService` / `SarvamTTSService`) for real-time, barge-in voice.
- **Real telephony** (Twilio/Plivo) for toll-free reach beyond the in-app channel.
- **Human-reviewed vernacular templates** for denial wording, rather than machine-translated from English.
- **Human review on low-confidence OCR scans**, rather than auto-accepting every read.

## Deployment

See `render.yaml` for the single-service Render deployment config. Push to a connected GitHub repo and Render
will build (`pip install -r src/requirements.txt`) and run (`python run.py`) automatically.
