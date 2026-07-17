# Sampoorna Health Secure — Technical Architecture & Design Decisions

This document is the deep technical reference for the claims-assistant PoC: how it's built, why each piece is
built that way, and every non-obvious decision made along the way. For the business framing (why this matters
to a buyer), see `docs/business-writeup.md`. For setup/run instructions, see the root `README.md`.

---

## 1. What this system does

A caller opens a (fictional) health-insurer app, taps **Call**, and has a turn-based voice conversation with an
AI assistant in their own Indian language, about three moments in a claims journey:

1. **Cashless pre-authorization** — before treatment. Explains how cashless works, checks pre-auth status.
2. **Reimbursement document completeness** — after treatment. Tells the caller what's missing, sends an
   in-app link to scan a document, and verifies it via OCR.
3. **Denial / short-payment explanation** — after adjudication. Explains exactly why a claim was denied or
   reduced, then escalates to a human agent with a logged case summary.

All three moments share one orchestration loop, one tool-calling contract, and one guardrail design.

---

## 2. Component architecture

```
Browser (vanilla HTML/CSS/JS)
  ├─ index.html        home screen
  ├─ call.html          voice call UI: mic capture, live captions, transcript, state banner
  ├─ upload.html        document scan + OCR verdict screen
  ├─ escalation.html    "connecting you to a human agent" screen
  └─ audit.html         metrics dashboard + per-session audit log viewer
        │
        │  fetch() / WebSocket
        ▼
FastAPI app (src/app.py)
  ├─ POST /session, GET /session/{id}, POST /session/{id}/intro
  ├─ POST /turn                 — one voice turn: STT → orchestrator → TTS
  ├─ POST /document             — OCR upload → classification → completeness check
  ├─ POST /session/{id}/language, /feedback
  ├─ GET /audit/{id}, /sessions, /metrics
  └─ WS /ws/live-transcribe     — proxies live captions during a turn
        │
        ├─ src/orchestrator.py   — the turn loop, tool contract, escalation rules
        ├─ src/knowledge.py      — deterministic JSON lookups ("retrieve" half of retrieve-then-explain)
        ├─ src/metrics.py        — aggregates session files into KPIs
        └─ src/sarvam/*          — one thin wrapper module per Sarvam API
              ├─ saaras.py       — speech-to-text (batch)
              ├─ live_stt.py     — speech-to-text (streaming, for live captions only)
              ├─ bulbul.py       — text-to-speech
              ├─ translate.py    — Sarvam-Translate
              ├─ llm.py          — Sarvam-105B chat completions (tool-calling)
              └─ vision.py       — doc-digitization (OCR) async job flow
        │
        ▼
src/data/*.json            — claims, policy KB, denial templates, cashless FAQ, document checklist
sessions/*.json            — one file per call session (state + audit log), gitignored
```

Everything runs as a single Render web service (`render.yaml`) — no queues, no database, no separate services.
That's a deliberate PoC-scope decision (see §9).

---

## 3. Tech stack and why

| Choice | Why |
|---|---|
| **Python + FastAPI** | Thin, fast to iterate, natural fit for wrapping five separate Sarvam REST/WS APIs behind one backend. |
| **Vanilla HTML/CSS/JS frontend, no framework** | The UI is five simple screens with no complex client state — a framework would be pure overhead for a PoC. |
| **JSON files for both the knowledge base and session storage** | No database needed at this data scale (six claims, ~80 KB entries, single-sitting demo). Explicit, readable, diffable in git. Named in the README as the first thing to swap for Postgres/Redis at production scale. |
| **No RAG / vector store** | The knowledge base is small and structured (claims, policy clauses, denial templates) — exact/keyword lookup is more predictable and auditable than embedding-based retrieval at this scale. |
| **No LangGraph / Pipecat / agent framework** | One LLM call per turn with a fixed tool set doesn't need a multi-agent graph; adding one would be unjustified complexity for what's currently a single-agent, turn-based flow. |
| **No real telephony (Twilio/Plivo)** | Out of scope for a PoC demoed in-browser; named explicitly as a production upgrade path. |

---

## 4. The core design: retrieve-then-explain

This is the single most important architectural decision in the system, and the one most worth demonstrating
to a buyer evaluating whether an LLM-driven claims assistant can be trusted not to invent coverage details.

**The problem:** Sarvam-105B (like any general LLM) will happily answer "is cataract covered?" or "why was my
claim denied?" from its own training-derived guesses if asked to directly. In insurance, a wrong guess about a
denial reason or a coverage limit is a compliance and trust problem, not just an annoying bug.

**The design:** Sarvam-105B is never asked to state a fact. It is only ever asked to pick which tool to call
and with what arguments — a narrow, cheap, ~50–150 token decision. The tool's Python implementation
(`src/knowledge.py`) does a deterministic JSON lookup and returns a structured result. That result is rendered
into an English sentence by a fixed Python template (`orchestrator._english_text_for_tool_result`), then
localized by **Sarvam-Translate** (a translation call, not a reasoning call) into the caller's language. The
LLM never sees or touches the final wording of a factual claim.

```
caller speech
   → Saaras (STT + language detection)
   → Sarvam-105B: "which tool, which arguments?"   ← the ONLY reasoning step
   → knowledge.py: deterministic JSON lookup         ← the ONLY source of facts
   → fixed Python template → English sentence
   → Sarvam-Translate → caller's language
   → Bulbul (TTS)
   → caller hears the reply
```

If a tool finds nothing (unknown claim ID, no matching FAQ), the template returns `None` and the turn is
marked **unresolved** rather than left to the LLM to improvise a save. See §6 for what happens next.

**A build note on latency:** Sarvam-105B produces a chain-of-thought (`reasoning_content`) before any answer,
even at `reasoning_effort: "low"`, which can be several hundred tokens even for a one-sentence reply. Confining
the LLM to tool-selection only (rather than also asking it to compose the final explanation) keeps this cost
paid once per turn instead of twice, and keeps regulated facts worded exactly as authored.

### Making the guardrail visible, not just claimed

Initially this design was real but invisible — a reviewer looking at a transcript couldn't tell an answer was
retrieved rather than invented. Every resolved turn now carries a `source` tag (`{tool, claim_id}`) from
`orchestrator.run_turn()` through to both the live call transcript (`call.html`) and the audit log
(`audit.html`), rendered as a small caption: *"Sourced from claim record CL-1003"* or *"Sourced from policy
knowledge base."* Escalations and clarifying questions correctly carry no source tag, since they aren't
retrieved facts.

---

## 5. The seven tools

Exposed to Sarvam-105B via OpenAI-style function-calling (`orchestrator.TOOLS`):

| Tool | Purpose | Backing lookup |
|---|---|---|
| `get_claim_status` | Claim status by claim ID or policy number | `claims.json` |
| `get_cashless_status` | Cashless pre-auth status by policy number | `claims.json` (filtered to `claim_type: cashless`) |
| `get_policy_clause` | General coverage/exclusion/waiting-period questions | `policy_kb.json` + `cashless_faq.json`, keyword-overlap matched |
| `get_denial_reason` | Why a claim was denied or paid less | `denial_templates.json`, enriched with `policy_kb.json` sub-limit/waiting-period/exclusion context |
| `check_document_completeness` | Which documents are still missing | `document_checklist.json` vs `claims.json.pending_documents` |
| `send_document_upload_link` | Sends the in-app "SMS" upload link | Same lookup as above; triggers the `REQUEST_DOCUMENT` action |
| `create_grievance_case` | Escalates to a human agent | Writes a case summary into the session, always sets `action: ESCALATE` |

`get_policy_clause` matching (`knowledge._tokenize` / `get_policy_clause`): query and FAQ text are lowercased,
stemmed (a small custom suffix-stripper — no NLTK dependency needed at this vocabulary size), and stopword-
filtered; the best-scoring FAQ entry wins if the token overlap is **≥ 2** words. That threshold was raised
from 1 after testing found a single shared word (e.g. "surgery") could falsely match an unrelated FAQ entry
(a query about pet surgery matching the human "cosmetic surgery" exclusion) — a subtle guardrail failure
where the retrieved record was real but wrong, not obviously "invented," and therefore easy to miss without
deliberately adversarial testing.

---

## 6. Turn resolution and escalation rules

Every turn is classified as **resolved** or **unresolved**, which drives the escalation budget:

- **Resolved:** a tool call found something and returned a renderable answer, OR the model asked a genuine
  clarifying question (no tool call, but has content) — e.g. "could you share your claim ID?" This counts as
  a normal part of the conversation, not a failure, and resets `failed_attempts` to 0.
- **Unresolved:** a tool was called but found nothing (unknown claim ID, no FAQ match). `failed_attempts`
  increments; on the second consecutive failure (`FAILED_ATTEMPT_LIMIT = 2`), the session auto-escalates with
  a case summary and a fallback message.

**Immediate escalation triggers** (bypass the failed-attempt counter entirely) fire when the caller: asks for
a human agent; sounds distressed; raises anything out of scope or high-stakes (medical/legal advice, fraud
allegations, IRDAI/ombudsman complaints); or when a claim is confirmed denied/reduced (denial explanations
always end in escalation — a human should own the follow-up conversation after a denial is explained).

An explicit **out-of-scope catch-all** was added after adversarial testing found the model would sometimes
answer or decline off-topic questions directly (weather, "tell me a joke") instead of escalating them — a
character-breaking failure mode a hiring-manager reviewer is likely to probe for first. The system prompt now
instructs an immediate `create_grievance_case` call for anything unrelated to the caller's policy, claims,
cashless authorization, or documents.

---

## 7. Language handling

- **No language picker.** Saaras auto-detects the spoken language per STT call; the detected code becomes the
  session's `language` and drives the TTS reply language for that turn.
- **Locked-in override, not per-turn re-detection for replies:** `session["language_override"]`, if set via
  `POST /session/{id}/language`, takes priority over the freshly detected language for that turn's *response*
  language — this exists so a caller (or, in a future iteration, a tap-to-correct control) can pin the reply
  language even if STT mis-detects a later utterance. No UI control currently sets this (see §11); it exists
  as a deliberate seam for language pinning without disrupting the auto-detect default.
- **Detected language is always shown** in the call UI's status chip (`langChip`), independent of the
  override, so the caller can see what the system thinks it heard.
- **Sarvam-Translate**, not Bulbul, is what performs localization of English template text — Bulbul only
  turns already-localized text into audio. Denial-reason and policy templates are authored once in English and
  translated per-turn rather than hand-translated per language, keeping the authored wording as the single
  source of truth for regulated content.

---

## 8. Voice UX design (client-side)

The call is turn-based (not real-time/barge-in), but several choices reduce how "walkie-talkie" it feels:

- **Live captions during the caller's turn** (`src/static/js/livecaption.js`): audio is streamed over a
  WebSocket to Sarvam's streaming STT (`live_stt.py`) purely to render a live transcript bubble as the caller
  speaks — this is cosmetic, not the transcript actually submitted (see next point).
- **Client-side end-of-turn detection, not Sarvam's VAD:** Sarvam's own `END_SPEECH` VAD signal fires on
  ordinary thinking pauses, cutting callers off mid-sentence. End-of-turn is instead decided locally from raw
  microphone RMS amplitude with a 3-second silence hold (`SILENCE_RMS_THRESHOLD`, `SILENCE_HOLD_MS` in
  `livecaption.js`), with a 20-second hard failsafe (`MAX_LISTEN_MS`) in case background noise never drops
  below threshold. This was a deliberate decoupling: use Sarvam's streaming STT for the visual "you're being
  heard" feedback, but keep app-controlled logic for the actual turn-boundary decision.
- **Perceived-latency mitigation:** a short "let me check that" filler clip is synthesized once
  (`_filler_audio_b64`) and cached client-side, then played immediately when the caller finishes speaking,
  *in parallel* with the real `/turn` network round-trip (`Promise` fired before `await`ing the filler audio
  in `call.html`). The caller hears an immediate acknowledgement instead of dead air while the actual lookup
  is still in flight — at zero added network cost, since the filler was already fetched during the *previous*
  turn's reply.
- **ID/policy-number normalization** (`knowledge._normalize_id`): claim IDs and policy numbers are matched by
  stripping all non-alphanumeric characters and uppercasing, since STT rarely reproduces a spoken ID's exact
  punctuation ("SMP HL 500123" vs "SMP-HL-500123" vs "smphl500123" all resolve to the same claim).

---

## 9. Session state and persistence

- **One JSON file per session** under `sessions/` (gitignored), keyed by a UUID. Chosen over an in-memory
  dict so a session survives an app process restart during a demo, and over a database because a PoC does
  not need query performance across sessions beyond a simple directory scan (`GET /sessions`).
- **30-minute idle timeout** (`SESSION_TIMEOUT_SECONDS`): a session older than that returns HTTP 410, and the
  frontend transparently starts a fresh session (`recoverFromMissingSession()`) rather than showing a raw
  error.
- **Render's free-tier disk is ephemeral** — session/audit data resets on every deploy or restart. This is
  explicitly called out in `render.yaml` as acceptable for a live, single-sitting demo, with the upgrade path
  (paid plan + persistent disk) named but not built.
- **Session-resume across screens:** navigating to the document-upload screen and back does not restart the
  call. `upload.html`'s "Return to call" button appends `?resume=1`; `call.html`'s `resumeCall()` then
  reconstructs UI state (language chip, last OCR verdict) from `GET /session/{id}` and `GET /audit/{id}`
  instead of replaying the full spoken introduction, so the call reads as continuous rather than restarted.

---

## 10. Document upload / OCR flow (Moment 2)

1. Orchestrator resolves a "send me the upload link" or "what documents are missing" request via
   `send_document_upload_link` / `check_document_completeness`, which sets `action: REQUEST_DOCUMENT`.
2. The call UI shows a simulated "SMS" toast with a link to `upload.html?session_id=...` — call state pauses
   here; there's no live-call/upload-screen concurrency to manage.
3. `upload.html` posts the photo to `POST /document`, which runs the **real** Sarvam doc-digitization job flow
   (`src/sarvam/vision.py`): create job → get an upload URL → PUT the file to blob storage → start the job →
   poll `status` until `Completed`/`Failed` → download a result zip → extract the `.md` OCR text. This is a
   genuine async job, not a mock — callers should expect several seconds of latency, not an instant response.
4. The OCR markdown is classified against the claim-type's document checklist by a second, narrowly-scoped
   LLM call (`orchestrator.classify_uploaded_document`) that is *forced* to call a `classify_document` tool
   with an enum constrained to the known checklist IDs plus `"unknown"` — this keeps classification bounded
   to a fixed vocabulary rather than free-text guessing.
5. `knowledge.check_document_completeness` recomputes what's still missing given the newly classified document,
   and the caller gets a spoken + written verdict.
6. **Synthetic sample documents** (`scripts/generate_sample_documents.py`) render five PIL-based images
   matching claim CL-1003, including a prescription rendered in Malayalam script (via Windows' `Nirmala.ttc`
   font) specifically to exercise Sarvam Vision's Indic-script OCR, not just English.

---

## 11. Metrics and audit

`src/metrics.py` scans every session file and computes:

- **Containment rate** — fraction of sessions that never escalated.
- **Language-wise containment** — same metric, bucketed by each session's first detected language.
- **Document-completeness-at-first-submission** — fraction of uploaded documents classified successfully (not
  `"unknown"`) on the first attempt.
- **Escalation quality** — fraction of escalations that produced a logged case summary (currently always
  100%, since every `create_grievance_case` call does so by construction; kept as a named metric because it's
  the kind of thing that could silently regress).
- **CSAT proxy** — thumbs-up/down ratio from `POST /session/{id}/feedback`.

`audit.html` surfaces all five as stat cards (the last two — escalation quality and CSAT — were computed but
not displayed until this was flagged as a gap; the first three were already visible), plus a per-session log
viewer showing each turn's transcript, reply, action, and now its source tag.

---

## 12. Frontend screen inventory

| Screen | Role |
|---|---|
| `index.html` | Entry point; "Call for help" / "Chat instead" both route to the same voice flow |
| `call.html` | Core voice UI: gate → intro → listen/speak loop → transcript with source captions → escalation/upload handoff |
| `upload.html` | Photo capture → processing spinner → OCR verdict → return-to-call (resume) |
| `escalation.html` | Terminal "connecting you to a human agent" screen |
| `audit.html` | KPI dashboard + session list + per-session turn-by-turn log |

Shared design system: `src/static/css/design.css` (one stylesheet, no per-screen duplication) and an inline
SVG Sarvam logo renderer (`src/static/js/logo.js`).

---

## 13. Deployment

Single Render web service (`render.yaml`): `pip install -r requirements.txt` then `python run.py`. One
environment secret (`SARVAM_API_KEY`, `sync: false` so it's set directly in Render's dashboard, never
committed). Free-tier plan; the ephemeral-disk tradeoff for session storage is documented inline in the
config file itself so it isn't a surprise during a later scale-up conversation.

---

## 14. Known limitations / production upgrade path (named, not built)

- **RAG / vector store** once the knowledge base scales past one insurer's ~80 entries.
- **LangGraph** for specialist sub-agents (cashless / reimbursement / compliance) once intents multiply beyond
  what a single tool-calling loop can cleanly arbitrate.
- **Pipecat** (`SarvamSTTService` / `SarvamTTSService`) for real-time, barge-in voice instead of turn-based.
- **Real telephony** (Twilio/Plivo) for reach beyond the in-app channel.
- **Database-backed sessions** once persistence needs to survive redeploys or scale past single-file-per-
  session lookups.
- **LLM tool-selection reliability** is inherently probabilistic — adversarial testing (§6) found and fixed
  two real gaps (a false-positive keyword match, an unreliable escalation trigger), but this class of issue
  can recur with prompt or model changes and warrants a standing adversarial test pass, not a one-time fix.
