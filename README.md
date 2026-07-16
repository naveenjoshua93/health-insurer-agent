# Sampoorna Health Secure — Claims Assistant (PoC)

A multilingual, voice-based health-insurance claims assistant built on Sarvam AI's API stack. A caller taps **Call**
inside the (fictional) Sampoorna Health Insurance app and talks to an AI assistant, in their own Indian language,
about three of the highest-friction moments in a claims journey.

**This is a proof-of-concept for a pre-sales assignment.** All insurer, policy, and claimant data is fictional.

---

## The three demo moments

1. **Cashless pre-authorization guidance** — before treatment. Explains how cashless works, checks pre-auth status.
2. **Reimbursement document completeness** — after treatment. Explains what documents are needed, and — via a
   simulated in-app SMS link — lets the caller scan a document, which Sarvam Vision reads to check completeness.
3. **Denial / short-payment explanation → grievance handoff** — after adjudication. Explains the exact reason a
   claim was denied or reduced, then automatically escalates to a human agent with a case summary.

## Why Sarvam

Every layer of the assistant is a genuine Sarvam API call, not a wrapper around a packaged product:

| Layer | Sarvam API | Role |
|---|---|---|
| Speech-to-text | **Saaras** (`saaras:v3`) | Transcribes the caller's speech, auto-detecting the spoken language |
| Text-to-speech | **Bulbul** | Speaks the assistant's reply back in the same language |
| Reasoning / tool-use | **Sarvam-105B** (Chat Completions) | Decides which claims tool to call, based on the caller's question |
| Localization | **Sarvam-Translate** | Renders the retrieved English fact into the caller's language — fast, deterministic, no chain-of-thought tax |
| Document intelligence | **Sarvam Vision** (doc-digitization) | Reads an uploaded claim document and extracts its text for classification |

**A build note on latency:** Sarvam-105B produces a chain-of-thought (`reasoning_content`) before any answer,
even at `reasoning_effort: "low"` — this can be several hundred tokens for a one-sentence reply. Rather than pay
that cost on every turn, the orchestrator uses Sarvam-105B **only** to decide which tool to call (a cheap,
~50–150 token decision), then renders the retrieved fact via the lightweight Sarvam-Translate API instead of
asking the reasoning model to compose an explanation. This keeps regulated facts (denial reasons, coverage
limits) exactly as authored, and keeps each turn fast and bounded.

## What's out of scope (deliberately)

No real telephony, no real SMS, no live claim adjudication, no fraud scoring, no RAG/vector store, no
LangGraph/Pipecat orchestration frameworks. See `docs/business-writeup.md` for the full rationale.

---

## Repository structure

```
/README.md
/run.py                  # entry point: `python run.py`
/requirements.txt
/.env.example
/src
  /data                  # claims.json, policy_kb.json, denial_templates.json, cashless_faq.json, document_checklist.json
  /sarvam                # saaras.py, bulbul.py, translate.py, llm.py, vision.py — one wrapper per Sarvam API
  knowledge.py            # deterministic JSON lookups + English answer assembly (the "retrieve" half of retrieve-then-explain)
  orchestrator.py          # the turn loop: tool-selection call -> deterministic lookup -> translate -> escalation rules
  metrics.py                # aggregates session files into containment/escalation/CSAT metrics
  app.py                     # FastAPI endpoints, serves /static
  /static                     # vanilla HTML/CSS/JS frontend (home, call, upload, escalation, audit screens)
/sessions                 # JSON-file session storage (gitignored)
/docs
  architecture-diagram.svg
  business-writeup.md
```

## Setup & run

1. **Prerequisites:** Python 3.11+, a Sarvam API key.
2. **Clone and enter the repo**, then:
   ```bash
   pip install -r requirements.txt
   cp .env.example .env   # then edit .env and set SARVAM_API_KEY=...
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

- **Moment 1:** Tap Call, ask *"Can I use cashless at any hospital?"* or *"Is ambulance covered?"* — answered from
  `cashless_faq.json` / `policy_kb.json`, translated into whatever language you spoke.
- **Moment 2:** Ask about reimbursement documents for a claim. When the assistant flags missing documents, a
  simulated SMS toast appears — tap it, upload a photo of a document, and watch the completeness verdict update.
- **Moment 3:** Ask why a claim was denied or paid less than expected. The assistant explains the specific reason
  (room-rent cap, waiting period, non-medical exclusion, etc.) and automatically hands off to a human agent with
  a logged case summary — visible at `/static/audit.html`.

Seeded claims are in [`src/data/claims.json`](src/data/claims.json) — six claims spanning pending, approved,
queried, partially-paid, and rejected states.

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
| `GET /metrics` | Aggregate containment rate, language-wise containment, doc-recognition rate, CSAT proxy |

## Production upgrade path (named, not built)

- **RAG / vector store** once the knowledge base scales past one insurer's ~80 entries.
- **LangGraph** for specialist sub-agents (cashless / reimbursement / compliance) once intents multiply.
- **Pipecat** (`SarvamSTTService` / `SarvamTTSService`) for real-time, barge-in voice.
- **Real telephony** (Twilio/Plivo) for toll-free reach beyond the in-app channel.

## Deployment

See `render.yaml` for the single-service Render deployment config. Push to a connected GitHub repo and Render
will build and run `python run.py` automatically.
